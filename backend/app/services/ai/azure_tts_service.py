"""
Service Azure Neural TTS pour HelloJADE.

Génère des fichiers audio WAV via le SDK azure-cognitiveservices-speech.
Les fichiers sont ensuite joués par Asterisk (Playback via ARI).

Voix : fr-BE-CharlineNeural (voix belge féminine d'Azure Cognitive Services).
"""
from __future__ import annotations

import asyncio
import os
import re
import tempfile
from typing import Optional

# Corrections de prononciation pour Azure fr-BE-CharlineNeural.
# Chaque entrée : (pattern regex, remplacement SSML avec <phoneme> IPA).
_PRONUNCIATION_FIXES: list[tuple[str, str]] = [
    # "dix" — Azure (fr-BE-CharlineNeural) ignore le s final en IPA → on force via <sub>
    (r"\bdix\b", '<sub alias="diss">dix</sub>'),
    # "quelque part" — liaison/prosodie parfois bancale
    (r"\bquelque part\b", '<phoneme alphabet="ipa" ph="kɛlkəpaʁ">quelque part</phoneme>'),
    # Liaisons orales avec trait d'union — Azure ne fait pas la liaison automatiquement
    # "soulagent-ils" → liaison T : "soulagent tils"
    (r"soulagent-ils", '<sub alias="soulagent tils">soulagent-ils</sub>'),
    # "concernait-elle" → liaison T : "concernait telle"
    (r"concernait-elle", '<sub alias="concernait telle">concernait-elle</sub>'),
    # "EpiCURA" — lettres majuscules lues comme acronyme → forcer lecture comme mot
    (r"\bEpiCURA\b", '<sub alias="Epicura">EpiCURA</sub>'),
]


def _fix_pronunciation(text: str) -> str:
    """Applique les corrections de prononciation avant injection dans le SSML."""
    for pattern, replacement in _PRONUNCIATION_FIXES:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_sdk_available = False
try:
    import azure.cognitiveservices.speech as speechsdk  # type: ignore
    _sdk_available = True
except ImportError:
    logger.warning("[AZURE_TTS] azure-cognitiveservices-speech non installé.")


class AzureTTSService:
    """
    Service TTS Azure Cognitive Services Neural.

    synthesize_to_bytes() génère l'audio WAV localement via le SDK Azure.
    Le fichier est ensuite placé dans TEMP_PATH et joué par Asterisk via ARI (Playback).
    """

    def __init__(self):
        self.speech_key = settings.AZURE_SPEECH_KEY
        self.speech_region = settings.AZURE_SPEECH_REGION
        self.voice_name = settings.AZURE_TTS_VOICE  # fr-BE-CharlineNeural

    @property
    def is_sdk_configured(self) -> bool:
        """True si le SDK Azure est installé ET les credentials présents."""
        return _sdk_available and bool(self.speech_key)

    def build_ssml(
        self,
        text: str,
        rate: str = "medium",
        pitch: str = "medium",
        lang: str = "fr-BE",
    ) -> str:
        """
        Construit un payload SSML pour Azure TTS.

        Permet de contrôler le débit, le ton et les pauses.
        """
        fixed = _fix_pronunciation(text)
        return (
            f'<speak version="1.0" '
            f'xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{lang}">'
            f'<voice name="{self.voice_name}">'
            f'<prosody rate="{rate}" pitch="{pitch}">{fixed}</prosody>'
            f"</voice></speak>"
        )

    async def synthesize_to_bytes(
        self,
        text: str,
        use_ssml: bool = False,
    ) -> Optional[bytes]:
        """
        Génère l'audio WAV via le SDK Azure Speech (hors-ligne, bytes en mémoire).

        Retourne None si le SDK n'est pas disponible ou en cas d'erreur.

        Args:
            text: Texte à synthétiser ou payload SSML si use_ssml=True.
            use_ssml: Si True, `text` est traité comme du SSML brut.
        """
        if not self.is_sdk_configured:
            logger.debug("[AZURE_TTS] SDK non disponible – synthesis skipped")
            return None

        try:
            return await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._synthesize_sync(text, use_ssml),
            )
        except Exception as exc:
            logger.error(f"[AZURE_TTS] Erreur synthesis: {exc}", exc_info=True)
            return None

    def _synthesize_sync(self, text: str, use_ssml: bool) -> Optional[bytes]:
        """Synthèse synchrone exécutée dans un thread (bloquant)."""
        config = speechsdk.SpeechConfig(
            subscription=self.speech_key,
            region=self.speech_region,
        )
        config.speech_synthesis_voice_name = self.voice_name
        config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Riff8Khz16BitMonoPcm
        )

        # Synthèse vers fichier temporaire (plus fiable que le pull stream)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            audio_cfg = speechsdk.audio.AudioOutputConfig(filename=tmp_path)
            synthesizer = speechsdk.SpeechSynthesizer(
                speech_config=config,
                audio_config=audio_cfg,
            )

            if use_ssml:
                result = synthesizer.speak_ssml_async(text).get()
            else:
                result = synthesizer.speak_text_async(text).get()

            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                with open(tmp_path, "rb") as f:
                    audio_bytes = f.read()
                logger.info(
                    f"[AZURE_TTS] Synthèse OK – {len(audio_bytes)} bytes, "
                    f"voice={self.voice_name}"
                )
                return audio_bytes
            else:
                details = ""
                if result.cancellation_details:
                    details = result.cancellation_details.error_details
                logger.error(
                    f"[AZURE_TTS] Échec synthesis: reason={result.reason} {details}"
                )
                return None
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


# Instance globale
azure_tts_service = AzureTTSService()
