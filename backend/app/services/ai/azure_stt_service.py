"""
Service Azure Speech-to-Text pour HelloJADE.

Transcrit les enregistrements audio WAV en texte via le SDK
azure-cognitiveservices-speech avec la locale fr-BE.

Si le SDK n'est pas installé, les méthodes retournent une chaîne vide.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.services.ai.medication_vocabulary import medication_vocabulary

logger = get_logger(__name__)

_sdk_available = False
try:
    import azure.cognitiveservices.speech as speechsdk  # type: ignore
    _sdk_available = True
except ImportError:
    logger.warning(
        "[AZURE_STT] azure-cognitiveservices-speech non installé. "
        "Transcription Azure indisponible."
    )


class AzureSTTService:
    """
    Service Speech-to-Text Azure Cognitive Services.

    Méthode principale : transcribe_url(audio_url) → str
    Télécharge le fichier WAV puis lance la transcription dans un thread
    pour ne pas bloquer la boucle asyncio.
    """

    def __init__(self):
        self.speech_key = settings.AZURE_SPEECH_KEY
        self.speech_region = settings.AZURE_SPEECH_REGION
        self.language = settings.AZURE_STT_LANGUAGE  # fr-BE

    @property
    def is_configured(self) -> bool:
        return _sdk_available and bool(self.speech_key)

    async def transcribe_url(self, audio_url: str) -> str:
        """
        Télécharge l'audio depuis l'URL et le transcrit.

        Args:
            audio_url: URL publique du fichier WAV (public_recording_urls.wav).

        Returns:
            Texte transcrit, ou chaîne vide si indisponible/erreur.
        """
        if not audio_url:
            return ""

        audio_bytes = await self._download(audio_url)
        if not audio_bytes:
            return ""

        return await self.transcribe_bytes(audio_bytes)

    async def transcribe_bytes(
        self,
        audio_bytes: bytes,
        use_medication_context: bool = False,
    ) -> str:
        """
        Transcrit des bytes audio WAV.

        Args:
            audio_bytes: Contenu du fichier audio WAV (16kHz, 16-bit, mono recommandé).
            use_medication_context: Si True, injecte le vocabulaire médicaments dans
                Azure PhraseListGrammar et normalise le transcript post-STT. À activer
                uniquement pour les questions portant sur le traitement médicamenteux.

        Returns:
            Texte transcrit (normalisé si use_medication_context=True) ou chaîne vide.
        """
        if not self.is_configured:
            logger.warning("[AZURE_STT] SDK non configuré – transcription ignorée")
            return ""

        # Écriture dans un fichier temporaire (le SDK exige un fichier)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            logger.info(f"[AZURE_STT] Submit: {len(audio_bytes)}B → Azure (med_ctx={use_medication_context})")
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._transcribe_sync(tmp_path, use_medication_context),
            )
            if use_medication_context:
                result = self._normalize_medications(result)
            return result
        except Exception as exc:
            logger.error(f"[AZURE_STT] Exception transcription: {exc}", exc_info=True)
            return ""
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _transcribe_sync(self, wav_path: str, use_medication_context: bool = False) -> str:
        """Transcription synchrone (exécutée dans un thread via run_in_executor)."""
        config = speechsdk.SpeechConfig(
            subscription=self.speech_key,
            region=self.speech_region,
        )
        config.speech_recognition_language = self.language

        # Garder les mots bruts sans censure (contexte médical)
        config.set_property(
            speechsdk.PropertyId.SpeechServiceResponse_ProfanityOption,
            "raw",
        )

        audio_cfg = speechsdk.audio.AudioConfig(filename=wav_path)
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=config,
            audio_config=audio_cfg,
        )

        if use_medication_context:
            self._inject_medication_phrase_list(recognizer)

        result = recognizer.recognize_once_async().get()

        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            text = result.text.strip()
            logger.info(f"[AZURE_STT] Transcription OK: '{text[:120]}'")
            return text

        if result.reason == speechsdk.ResultReason.NoMatch:
            logger.info(
                f"[AZURE_STT] NoMatch – aucune parole détectée: "
                f"{result.no_match_details}"
            )
            return ""

        # Erreur ou annulation
        details = ""
        if result.cancellation_details:
            details = result.cancellation_details.error_details
        logger.error(f"[AZURE_STT] Erreur: reason={result.reason} – {details}")
        return ""

    def _inject_medication_phrase_list(self, recognizer) -> None:
        """Injecte les noms de médicaments dans le PhraseListGrammar du recognizer."""
        try:
            phrase_list = speechsdk.PhraseListGrammar.from_recognizer(recognizer)
            for phrase in medication_vocabulary.get_phrase_list_entries():
                phrase_list.addPhrase(phrase)
        except Exception as exc:
            logger.warning(f"[AZURE_STT] Injection phrase list échouée: {exc}")

    def _normalize_medications(self, text: str) -> str:
        """Applique la normalisation post-STT des noms de médicaments."""
        if not text:
            return text
        try:
            from app.services.ai.medication_normalizer import normalize_transcript
            return normalize_transcript(text)
        except Exception as exc:
            logger.warning(f"[AZURE_STT] Normalisation médicaments échouée: {exc}")
            return text

    async def _download(self, url: str) -> Optional[bytes]:
        """Télécharge un fichier audio depuis une URL avec timeout de 30 s."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                logger.info(
                    f"[AZURE_STT] Audio téléchargé: {len(resp.content)} bytes"
                )
                return resp.content
        except Exception as exc:
            logger.error(f"[AZURE_STT] Erreur téléchargement {url}: {exc}")
            return None

    def create_push_stream(self):
        """
        Crée un PushAudioInputStream + SpeechRecognizer en mode reconnaissance continue.

        Utilisé pour le streaming temps réel (audio mulaw converti en PCM 16-bit).
        Le format d'entrée est 8 kHz, 16-bit, mono (après conversion audioop.ulaw2lin).

        Returns:
            (push_stream, recognizer, results) ou (None, None, []) si SDK indisponible.

        Usage:
            push_stream, recognizer, results = azure_stt_service.create_push_stream()
            recognizer.start_continuous_recognition_async()
            # ... push PCM frames via push_stream.write(pcm_bytes)
            push_stream.close()  # déclenche la finalisation
            recognizer.stop_continuous_recognition_async().get()
            transcription = " ".join(results)
        """
        if not self.is_configured:
            logger.warning("[AZURE_STT] SDK non configuré – streaming indisponible")
            return None, None, []

        results = []

        stream_format = speechsdk.audio.AudioStreamFormat(
            samples_per_second=8000,
            bits_per_sample=16,
            channels=1,
        )
        push_stream = speechsdk.audio.PushAudioInputStream(stream_format=stream_format)

        speech_config = speechsdk.SpeechConfig(
            subscription=self.speech_key,
            region=self.speech_region,
        )
        # fr-FR utilisé pour le streaming : précision nettement supérieure à fr-BE
        # sur PSTN 8kHz (Azure a ~10x plus de données d'entraînement pour fr-FR).
        # fr-FR couvre très bien le français belge standard en pratique.
        speech_config.speech_recognition_language = "fr-FR"
        speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceResponse_ProfanityOption,
            "raw",
        )
        # Délai de silence avant de considérer la fin de parole
        # 1500ms : robustesse sur PSTN 8kHz (réponses courtes, pauses naturelles)
        speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs,
            "1500",
        )
        # Délai max d'attente avant que le patient commence à parler (5s)
        speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs,
            "5000",
        )

        audio_config = speechsdk.audio.AudioConfig(stream=push_stream)
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )

        # Injection vocabulaire médicaments
        self._inject_medication_phrase_list(recognizer)

        def _on_recognized(evt):
            if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
                text = evt.result.text.strip()
                if text:
                    text = self._normalize_medications(text)
                    results.append(text)
                    logger.info(f"[AZURE_STT_STREAM] Segment reconnu: '{text[:120]}'")

        def _on_canceled(evt):
            if evt.result.cancellation_details:
                logger.warning(
                    f"[AZURE_STT_STREAM] Annulé: {evt.result.cancellation_details.error_details}"
                )

        recognizer.recognized.connect(_on_recognized)
        recognizer.canceled.connect(_on_canceled)

        return push_stream, recognizer, results


# Instance globale
azure_stt_service = AzureSTTService()
