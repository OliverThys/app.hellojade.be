"""
Service d'appels automatisés — Asterisk ARI + OVH SIP Trunk.

Stack :
  TTS  → Azure Cognitive Services Neural (fr-BE-CharlineNeural) → WAV → Asterisk Playback
  STT  → Azure Cognitive Services Speech SDK (sur fichier WAV enregistré par Asterisk)
  LLM  → Mistral API mistral-small-latest (parsing réponse + détection alerte)
  PBX  → Asterisk 20 LTS via ARI (REST + WebSocket events)
  SIP  → OVH SIP Trunk (PJSIP, G.711 alaw)
  State→ Redis (multi-workers safe)

Flow par appel :
  1. POST /api/v1/calls/originate → originate()
       ARI crée le channel sortant → patient sonne
  2. StasisStart (patient décroche) → _on_stasis_start()
       Génère WAV bienvenue → Playback
  3. PlaybackFinished (bienvenue) → _on_playback_finished()
       Génère WAV question → Playback
  4. PlaybackFinished (question) → Record
  5. RecordingFinished → ack immédiat (WAV "D'accord") + background (Azure STT → Mistral)
  6. PlaybackFinished (ack) → question suivante ou clôture
  7. Fin du questionnaire : si alerte → WAV alerte → Redirect infirmières ; sinon clôture normale
  8. ChannelHangupRequest / StasisEnd → sauvegarde DB + nettoyage Redis
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import shutil
import time
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import redis.asyncio as aioredis
import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from app.core.config import settings
from app.core.logging import get_logger
from app.services.ai.azure_stt_service import azure_stt_service
from app.services.call_settings_service import call_settings_service, next_valid_window
from app.services.ai.azure_tts_service import azure_tts_service
from app.services.ai.mistral_service import mistral_service
from app.services.telephony.questionnaire import (
    ACK_ENTRIES_NEUTRAL,
    CLOSING_MESSAGE_ALERT,
    CLOSING_MESSAGE_NORMAL,
    CLOSING_MESSAGE_NORMAL_PROCHE,
    CLOSING_MESSAGE_TRANSFER_FAILED,
    CLOSING_MESSAGE_TRANSFER_FAILED_PROCHE,
    CONSENT_QUESTION,
    CONSENT_QUESTION_PROCHE,
    CONSENT_REFUSED_MESSAGE,
    NO_ACTIVE_QUESTIONS_MESSAGE,
    OUT_OF_SCOPE_MESSAGE,
    PERSON_CHECK_QUESTION,
    PERSON_CHECK_RETRY,
    PERSON_NOT_FOUND_MESSAGE,
    PROCHE_QUESTION,
    QUESTIONNAIRE,
    RETRY_PREFIXES,
    SKIP_MESSAGE,
    WELCOME_MESSAGE,
    short_reprompt_after_out_of_scope,
)

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────────────────────────────────────

REDIS_PREFIX = "ari_call:"
REDIS_TTL = 7200  # 2 heures

# Durées d'enregistrement
RECORD_DURATION_SHORT = 10
RECORD_DURATION_LONG = 20
SILENCE_TIMEOUT = 1          # secondes de silence = fin de parole (fallback si TALK_DETECT échoue)

UNCLEAR_CONFIDENCE_THRESHOLD = 0.15
UNCLEAR_MAX_RETRIES = 1

# Silence timeout différencié :
# - SILENCE_TIMEOUT     : délai initial (patient n'a pas encore parlé) → laisse le temps de réfléchir
# - END_SILENCE_TIMEOUT : délai après le dernier mot → coupe plus vite une fois la phrase terminée
END_SILENCE_TIMEOUT = 1.0   # secondes après le dernier mot du patient

# Durée minimale de lecture d'un ACK avant de le couper si l'analyse est déjà prête.
# Évite qu'un son soit tranché trop tôt (ex: "Hm—" au lieu de "Hum hum.").
# 0.7s = ~50 % de "Hum hum." (1.4s) ; les phrases courtes (D'accord. ~0.5s) se terminent
# naturellement avant ce seuil et ne sont donc jamais coupées.
ACK_MIN_PLAY_S = 0.7

# Vérification destinataire (oui/non)
IDENTITY_YESNO_RECORD_DURATION = 8  # secondes d'enregistrement pour les questions oui/non

# Answering Machine Detection (AMD)
AMD_QUICK_ANSWER_MS = 1500          # décrochage < 1.5s = répondeur probable
AMD_MACHINE_PATTERNS = [            # patterns STT caractéristiques d'un répondeur
    "laissez un message", "laissez votre message", "après le bip",
    "after the beep", "not available", "leave a message",
    "messagerie", "boîte vocale", "voicemail", "voice mail",
    "veuillez laisser", "bip sonore", "nous sommes absents",
    "rappellerons", "laisser un message", "beep",
]

# Codes cause Q.850 pour les appels sans réponse (Asterisk 20.14+)
CAUSE_BUSY       = 17
CAUSE_NO_ANSWER  = 19
CAUSE_REJECTED   = 21

# Répertoire TTS : partagé avec Asterisk via lien symbolique
# Backend Docker : /app/temp/tts → host hellojade/temp/tts → Asterisk custom/
TTS_DIR = Path(settings.TEMP_PATH) / "tts"

# Sous-répertoire du cache content-addressé (fichiers persistants, jamais supprimés)
# Les fichiers sont nommés {sha256[:16]}.wav et réutilisés entre appels.
TTS_CACHE_DIR = TTS_DIR / "cache"

# Son relatif au répertoire custom d'Asterisk (sound:custom/filename_sans_extension)
# Asterisk cherche /var/lib/asterisk/sounds/custom → lien vers hellojade/temp/tts
ASTERISK_SOUNDS_PREFIX = "custom"

# Phrases multi-mots (substring safe) signalant que le patient n'a pas compris.
_META_RESPONSE_KEYWORDS = (
    "pas compris", "pas bien compris", "n'ai pas compris",
    "comprends pas", "je ne comprends pas",
    "vous pouvez répéter", "pouvez-vous répéter",
    "n'ai pas entendu", "pas entendu ce que",
    "c'est quoi la question",
)

# Mots seuls — vérifiés uniquement si le transcript est très court (≤ 3 mots)
# pour éviter les faux positifs ("pardon de vous déranger" → valide réponse)
_META_SHORT_WORDS = frozenset({
    "pardon", "hein", "quoi", "comment", "répétez",
    "répète", "re ?", "quoi ?", "hein ?",
})

# ─────────────────────────────────────────────────────────────────────────────
# ÉTATS
# ─────────────────────────────────────────────────────────────────────────────

class CallState(str, Enum):
    INITIATED       = "initiated"
    RINGING         = "ringing"
    ANSWERED        = "answered"
    WELCOME         = "welcome"
    RECIPIENT_CHECK = "recipient_check"   # "êtes-vous bien X ?"
    PROCHE_CHECK    = "proche_check"      # "êtes-vous un proche ?"
    CONSENT_CHECK   = "consent_check"     # "avez-vous quelques minutes ?"
    QUESTIONING     = "questioning"
    RECORDING       = "recording"
    ANALYZING       = "analyzing"
    ALERT_DETECTED  = "alert_detected"
    TRANSFERRING    = "transferring"
    CLOSING         = "closing"
    COMPLETED       = "completed"
    FAILED          = "failed"


# ─────────────────────────────────────────────────────────────────────────────
# REDIS
# ─────────────────────────────────────────────────────────────────────────────

_redis_client: Optional[aioredis.Redis] = None


async def _get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            str(settings.REDIS_URL),
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


def _extract_q6_symptom_detail(answers: list) -> Optional[str]:
    """
    Extrait la description du symptôme signalé en Q6 pour enrichir call_metadata.

    Priorité :
      1. Transcript de Q6a_symptome_detail (réponse ouverte demandée après Q6=oui)
      2. Notes du LLM sur Q6_autres_symptomes (symptôme déduit implicitement, Partie 1)
    Retourne None si Q6 n'a pas déclenché d'alerte ou si aucune description n'est disponible.
    """
    for ans in answers:
        if ans.get("question_id") == "Q6a_symptome_detail":
            transcript = (ans.get("transcript") or "").strip()
            if transcript:
                return transcript
            parsed_answer = (ans.get("parsed", {}).get("answer") or "").strip()
            if parsed_answer:
                return parsed_answer
    for ans in answers:
        if ans.get("question_id") == "Q6_autres_symptomes":
            notes = (ans.get("parsed", {}).get("notes") or "").strip()
            if notes and notes != "pré-répondu par anticipation":
                return notes
    return None


# ─────────────────────────────────────────────────────────────────────────────
# DÉTECTION OUI / NON
# ─────────────────────────────────────────────────────────────────────────────

_OUI_KEYWORDS: frozenset[str] = frozenset({
    "oui", "ouais", "bien sûr", "effectivement", "absolument", "tout à fait",
    "c'est moi", "c'est bien moi", "c'est exact", "correct", "affirmatif",
    "bien entendu", "certainement", "volontiers", "avec plaisir",
})

_NON_KEYWORDS: frozenset[str] = frozenset({
    "non", "nan", "pas moi", "pas du tout", "absolument pas",
    "ce n'est pas moi", "c'est pas moi", "je ne suis pas",
    "négatif", "incorrect", "jamais",
})


def _detect_yesno(transcript: str) -> Optional[bool]:
    """Détecte oui (True) / non (False) dans un transcript court.

    Retourne None si la réponse est incompréhensible.
    """
    if not transcript.strip():
        return None
    t = transcript.lower()
    has_oui = any(kw in t for kw in _OUI_KEYWORDS)
    has_non = any(kw in t for kw in _NON_KEYWORDS)
    if has_oui and not has_non:
        return True
    if has_non and not has_oui:
        return False
    return None


# ─────────────────────────────────────────────────────────────────────────────
# FAST-PATH YESNO — court-circuite Mistral pour les réponses évidentes
# ─────────────────────────────────────────────────────────────────────────────

_FAST_YES_STARTERS = frozenset(["oui", "ouais", "si"])
_FAST_NO_STARTERS  = frozenset(["non", "nan"])

# Mots qui indiquent une réponse complexe → laisser Mistral traiter
_FAST_EXCLUDE = (
    "mais ", "par contre", "sauf ", "cependant", "toutefois",
    "j'ai ", "j'", "je ", "ma ", "mon ", "mes ",
    "sang", "douleur", "mal ", "fièvre", "nausée", "vomi",
    "respir", "gonfle", "enfle", "brûle", "saigne",
)


def _fast_yesno_parse(transcript: str) -> Optional[Dict[str, Any]]:
    """
    Retourne un parsed dict pour les réponses yesno non-ambiguës (≤ 4 mots,
    pas de description de symptôme, pas de nuance) afin d'éviter l'appel Mistral.
    Retourne None si le transcript mérite une analyse LLM complète.
    """
    t = transcript.lower().strip()
    if not t:
        return None
    words = t.split()
    if len(words) > 4:
        return None
    # Ne pas fast-pather si la réponse contient un marqueur complexifiant
    if any(excl in t for excl in _FAST_EXCLUDE):
        return None
    # Strip ponctuation collée (ex. "oui," "non." "oui?") pour comparer correctement
    first = words[0].strip("?.!,;:")
    if first in _FAST_YES_STARTERS:
        return {
            "answer": "oui", "confidence": 0.95,
            "understood": True, "out_of_scope": False,
            "notes": None, "pre_answered": {},
        }
    if first in _FAST_NO_STARTERS:
        return {
            "answer": "non", "confidence": 0.95,
            "understood": True, "out_of_scope": False,
            "notes": None, "pre_answered": {},
        }
    return None


# ─────────────────────────────────────────────────────────────────────────────
# SERVICE PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

class AsteriskARIService:
    """
    Orchestrateur des appels automatisés via Asterisk ARI.

    Maintient une connexion WebSocket permanente à Asterisk pour recevoir
    les événements (StasisStart, PlaybackFinished, RecordingFinished, etc.)
    et effectue les actions via l'API REST ARI (httpx).

    L'état de chaque appel est stocké dans Redis → multi-workers safe.
    """

    def __init__(self) -> None:
        self.base_url = settings.ASTERISK_ARI_URL.rstrip("/")
        self.ari_user = settings.ASTERISK_ARI_USER
        self.ari_password = settings.ASTERISK_ARI_PASSWORD
        self.app_name = settings.ASTERISK_ARI_APP
        self.caller_number = settings.ASTERISK_CALLER_NUMBER
        self.trunk = settings.ASTERISK_TRUNK
        # transfer_number et transfer_mode sont lus dynamiquement depuis settings
        # (ne pas cacher ici : la config DB peut les surcharger après l'init)
        self._ws_task: Optional[asyncio.Task] = None
        # Timers de fin de parole par channel (TALK_DETECT → END_SILENCE_TIMEOUT)
        self._end_silence_tasks: Dict[str, asyncio.Task] = {}
        TTS_DIR.mkdir(parents=True, exist_ok=True)
        TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def is_configured(self) -> bool:
        return bool(
            self.ari_user
            and self.ari_password
            and self.caller_number
        )

    # ── HTTP REST ────────────────────────────────────────────────────────────

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"{self.base_url}/ari",
            auth=(self.ari_user, self.ari_password),
            timeout=10.0,
        )

    async def _post(self, path: str, **params: Any) -> Optional[Dict]:
        async with self._client() as c:
            r = await c.post(path, params=params)
            if r.status_code not in (200, 201, 204):
                logger.error(f"[ARI] POST {path} → {r.status_code}: {r.text}")
                return None
            return r.json() if r.content else None

    async def _delete(self, path: str, **params: Any) -> bool:
        async with self._client() as c:
            r = await c.delete(path, params=params)
            return r.status_code in (200, 204)

    async def _stop_playback(self, channel_id: str, playback_id: str) -> bool:
        """Arrête la lecture en cours (barge-in patient pendant TTS)."""
        if not playback_id:
            return False
        return await self._delete(f"/playbacks/{playback_id}")

    async def _get(self, path: str) -> Optional[Dict]:
        async with self._client() as c:
            r = await c.get(path)
            return r.json() if r.status_code == 200 else None

    # ── Redis state ──────────────────────────────────────────────────────────

    @staticmethod
    def _redis_key(channel_id: str) -> str:
        return f"{REDIS_PREFIX}{channel_id}"

    async def _get_state(self, channel_id: str) -> Optional[Dict[str, Any]]:
        try:
            redis = await _get_redis()
            data = await redis.get(self._redis_key(channel_id))
            return json.loads(data) if data else None
        except Exception as exc:
            logger.error(f"[ARI] Redis get error: {exc}")
            return None

    async def _save_state(self, channel_id: str, state: Dict[str, Any]) -> None:
        try:
            redis = await _get_redis()
            await redis.setex(
                self._redis_key(channel_id),
                REDIS_TTL,
                json.dumps(state, default=str),
            )
        except Exception as exc:
            logger.error(f"[ARI] Redis save error: {exc}")

    async def _delete_state(self, channel_id: str) -> None:
        try:
            redis = await _get_redis()
            await redis.delete(self._redis_key(channel_id))
        except Exception:
            pass

    @staticmethod
    def _questionnaire(state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Retourne le questionnaire figé pour cet appel.
        Sélectionne le questionnaire proche si caller_role == "proche" et qu'il est chargé,
        sinon retourne le questionnaire patient. Repli sur QUESTIONNAIRE Python si rien en DB.
        """
        caller_role = state.get("caller_role") or "patient"
        if caller_role == "proche" and "_questionnaire_proche" in state:
            return state["_questionnaire_proche"]
        if "_questionnaire_patient" in state:
            return state["_questionnaire_patient"]
        # Compat avec ancienne clé (ne devrait plus arriver)
        if "_questionnaire" in state:
            return state["_questionnaire"]
        return QUESTIONNAIRE

    async def _hydrate_questionnaire_from_db(self, state: Dict[str, Any]) -> None:
        """
        Précharge les questionnaires patient ET proche au début de l'appel (une seule fois).
        Les deux sont stockés séparément ; _questionnaire() sélectionne au moment voulu.
        """
        if "_questionnaire_patient" in state:
            return
        service_code = state.get("patient_service_code") or None
        try:
            from app.database import AsyncSessionLocal
            from app.services.telephony.questionnaire_loader import load_questionnaire_for_service

            async with AsyncSessionLocal() as db:
                qs_patient = await load_questionnaire_for_service(
                    db, service_code=service_code, caller_role="patient"
                )
                qs_proche = await load_questionnaire_for_service(
                    db, service_code=service_code, caller_role="proche"
                )
            state["_questionnaire_patient"] = qs_patient
            state["_questionnaire_proche"] = qs_proche
            state.pop("_questionnaire", None)  # nettoyer ancienne clé si présente
            logger.info(
                f"[ARI] Questionnaires chargés — patient: {len(qs_patient)} blocs, "
                f"proche: {len(qs_proche)} blocs (service={service_code!r})"
            )
        except Exception as exc:
            logger.warning(f"[ARI] Impossible de charger les questionnaires DB — repli Python: {exc}")

    async def _hydrate_messages_from_db(self, state: Dict[str, Any]) -> None:
        """
        Précharge les messages (welcome + outros) patient ET proche depuis la DB.
        _get_message() sélectionne le bon set selon caller_role au moment de l'appel.
        """
        if "_messages_patient" in state:
            return
        service_code = state.get("patient_service_code") or None
        try:
            from app.database import AsyncSessionLocal
            from app.services.telephony.questionnaire_loader import load_messages_for_service
            async with AsyncSessionLocal() as _db:
                msgs_patient = await load_messages_for_service(
                    _db, service_code=service_code, caller_role="patient"
                )
                msgs_proche = await load_messages_for_service(
                    _db, service_code=service_code, caller_role="proche"
                )
            state["_messages_patient"] = msgs_patient
            state["_messages_proche"] = msgs_proche
            state.pop("_messages", None)  # nettoyer ancienne clé
            logger.info(f"[ARI] Messages chargés depuis DB (service={service_code!r})")
        except Exception as exc:
            logger.warning(f"[ARI] Impossible de charger les messages DB: {exc}")
            state["_messages_patient"] = {}
            state["_messages_proche"] = {}

    def _get_message(self, state: Dict[str, Any], key: str, fallback: str) -> str:
        """Retourne le message DB pour la clé donnée, avec interpolation patient et fallback."""
        caller_role = state.get("caller_role") or "patient"
        if caller_role == "proche":
            msgs = state.get("_messages_proche") or state.get("_messages") or {}
        else:
            msgs = state.get("_messages_patient") or state.get("_messages") or {}
        template = msgs.get(key) or fallback
        return (
            template
            .replace("{{civilité}}", state.get("patient_civilite", ""))
            .replace("{{prénom}}", state.get("patient_prenom", ""))
            .replace("{{nom}}", state.get("patient_nom", ""))
            .strip()
        )

    # ── Message d'accueil dynamique ─────────────────────────────────────────

    async def _get_welcome_message(self, state: Dict[str, Any]) -> str:
        """Retourne le message d'accueil interpolé (utilise le cache _messages du state)."""
        return self._get_message(state, "welcome", WELCOME_MESSAGE)

    # ── TTS → fichier WAV ───────────────────────────────────────────────────

    async def _synthesize(self, text: str, filename_hint: str = "", use_ssml: bool = False) -> Optional[str]:
        """
        Génère un fichier WAV via Azure TTS avec cache content-addressé.

        Le SSML est hashé (SHA-256, 16 hex) → le fichier est stocké dans TTS_CACHE_DIR
        sous le nom {hash}.wav et réutilisé sans appel Azure si déjà présent.

        Retourne le chemin relatif SANS extension pour Asterisk : "cache/{hash}" ou
        None en cas d'échec.
        """
        if not use_ssml:
            text = azure_tts_service.build_ssml(text)
            use_ssml = True

        # Cache content-addressé : hash du SSML → fichier persistant
        cache_key = hashlib.sha256(text.encode()).hexdigest()[:16]
        cache_path = TTS_CACHE_DIR / f"{cache_key}.wav"

        if cache_path.exists():
            logger.info(f"[ARI] TTS cache HIT → {cache_key} (hint={filename_hint!r})")
            return f"cache/{cache_key}"

        logger.info(f"[ARI] TTS cache MISS → synthèse Azure (hint={filename_hint!r})")
        audio_bytes = await azure_tts_service.synthesize_to_bytes(text, use_ssml=True)
        if not audio_bytes:
            logger.error(f"[ARI] TTS échec pour hint={filename_hint!r}")
            return None

        cache_path.write_bytes(audio_bytes)
        logger.info(
            f"[ARI] TTS synthétisé → {cache_key} "
            f"({len(audio_bytes)} bytes, hint={filename_hint!r})"
        )
        return f"cache/{cache_key}"

    def _static(self, key: str) -> Optional[str]:
        """Retourne le chemin relatif du fichier WAV statique pré-généré si présent.

        Les fichiers statiques sont dans TTS_CACHE_DIR sous le nom static_{key}.wav.
        Retourne None si le fichier n'existe pas (le code appellera alors _synthesize).
        """
        path = TTS_CACHE_DIR / f"static_{key}.wav"
        return f"cache/static_{key}" if path.exists() else None

    def _cleanup_tts(self, filename: str) -> None:
        """Supprime le fichier WAV TTS après lecture.

        Les fichiers dans le cache (préfixe 'cache/') sont persistants et ne sont
        jamais supprimés ici — ils survivent entre les appels.
        """
        if filename.startswith("cache/"):
            return
        try:
            (TTS_DIR / f"{filename}.wav").unlink(missing_ok=True)
        except Exception:
            pass

    # ── Actions ARI ─────────────────────────────────────────────────────────

    async def _play(self, channel_id: str, sound_name: str) -> Optional[str]:
        """
        Lance la lecture d'un son sur le channel.
        sound_name : nom relatif Asterisk (ex: "custom/mon_fichier")
        Retourne le playback_id.
        """
        playback_id = uuid.uuid4().hex
        result = await self._post(
            f"/channels/{channel_id}/play/{playback_id}",
            media=f"sound:{sound_name}",
        )
        if result is not None:
            logger.info(f"[ARI] TTS play: {sound_name} (channel: {channel_id})")
            return playback_id
        return None

    async def _record(self, channel_id: str, recording_name: str, max_duration: int) -> bool:
        """Lance l'enregistrement sur le channel."""
        cs = await call_settings_service.get()
        silence_timeout = int(cs.get("silence_timeout_seconds", SILENCE_TIMEOUT))
        result = await self._post(
            f"/channels/{channel_id}/record",
            name=recording_name,
            format="wav",
            maxDurationSeconds=max_duration,
            maxSilenceSeconds=silence_timeout,
            ifExists="overwrite",
            beep=False,
        )
        if result is not None:
            logger.info(f"[ARI] Recording start: {recording_name} silence={silence_timeout}s (channel: {channel_id})")
        return result is not None

    async def _hangup(self, channel_id: str) -> None:
        await self._delete(f"/channels/{channel_id}")

    async def _stt_from_recording(self, recording_name: str) -> str:
        """Lit un fichier WAV Asterisk et retourne le transcript Azure STT."""
        recording_path = f"/var/spool/asterisk/recording/{recording_name}.wav"
        try:
            with open(recording_path, "rb") as f:
                audio_bytes = f.read()
            return await azure_stt_service.transcribe_bytes(audio_bytes)
        except (FileNotFoundError, PermissionError) as exc:
            logger.warning(f"[ARI] Enregistrement inaccessible: {recording_path} – {exc}")
            return ""

    async def _continue_transfer(self, channel_id: str, callee: str) -> bool:
        """Transfert réel : repasse le channel dans le dialplan hellojade-transfer
        qui exécute Dial(PJSIP/{callee}@trunk). Fiable même avec des mobiles (pas de REFER/302).
        """
        async with self._client() as c:
            r = await c.post(
                f"/channels/{channel_id}/continue",
                params={"context": "hellojade-transfer", "extension": callee, "priority": 1},
            )
        if r.status_code not in (200, 204):
            logger.error(f"[ARI] continue transfer → {r.status_code}: {r.text}")
            return False
        return True

    async def _enable_talk_detect(self, channel_id: str) -> None:
        """Active TALK_DETECT sur le channel pour la détection fin-de-parole."""
        try:
            async with self._client() as c:
                r = await c.post(
                    f"/channels/{channel_id}/variable",
                    params={"variable": "TALK_DETECT(set)", "value": ""},
                )
            if r.status_code not in (200, 201, 204):
                logger.warning(
                    f"[ARI] TALK_DETECT enable échec {r.status_code}: {r.text} "
                    f"(channel: {channel_id})"
                )
            else:
                logger.info(f"[ARI] TALK_DETECT activé (channel: {channel_id})")
        except Exception as exc:
            logger.warning(f"[ARI] TALK_DETECT enable exception: {exc} (channel: {channel_id})")

    async def _on_channel_talking_started(self, event: Dict[str, Any]) -> None:
        """TALK_DETECT : barge-in TTS, indice répondeur, ou annulation timer fin-de-parole."""
        channel_id = event.get("channel", {}).get("id")
        if not channel_id:
            return
        logger.info(f"[ARI] Patient parle (channel: {channel_id})")

        # Annule le timer END_SILENCE si le patient reprend la parole (pause mid-phrase)
        existing = self._end_silence_tasks.pop(channel_id, None)
        if existing:
            existing.cancel()

        state = await self._get_state(channel_id)
        if not state:
            return

        if settings.VOICE_BARGE_IN_ENABLED:
            role = state.get("last_playback_role")
            pb_id = state.get("last_playback_id")
            if role in ("welcome", "recipient_question", "question") and pb_id:
                ok = await self._stop_playback(channel_id, pb_id)
                if ok:
                    logger.info(f"[ARI] Barge-in : TTS interrompu (role={role})")
                    return

        answer_ts = state.get("answer_timestamp", 0)
        elapsed_ms = (time.time() - answer_ts) * 1000
        if elapsed_ms <= AMD_QUICK_ANSWER_MS:
            logger.info(f"[ARI] AMD suspect: parole à {elapsed_ms:.0f}ms après décrochage")
            state["_amd_suspect"] = True
            await self._save_state(channel_id, state)

    # États dans lesquels un enregistrement actif peut être court-circuité par TALK_DETECT
    _ACTIVE_RECORDING_STATES = {
        CallState.RECORDING,
        CallState.RECIPIENT_CHECK,
        CallState.PROCHE_CHECK,
        CallState.CONSENT_CHECK,
    }

    async def _on_channel_talking_finished(self, event: Dict[str, Any]) -> None:
        """TALK_DETECT : le patient vient de se taire.

        Lance un timer END_SILENCE_TIMEOUT. S'il n'a pas reparlé au bout
        de ce délai, on arrête l'enregistrement manuellement — plus court que le
        maxSilenceSeconds d'Asterisk qui couvre le silence initial.
        Couvre tous les états avec un enregistrement actif (questions, PersonCheck, Consent).
        """
        channel_id = event.get("channel", {}).get("id")
        if not channel_id:
            return

        state = await self._get_state(channel_id)
        if not state or state.get("state") not in self._ACTIVE_RECORDING_STATES:
            return
        logger.info(f"[ARI] Patient silence — timer {END_SILENCE_TIMEOUT}s (channel: {channel_id})")

        recording_name = state.get("last_recording_name")
        if not recording_name:
            return

        current_state = state.get("state")

        async def _stop_after_end_silence() -> None:
            await asyncio.sleep(END_SILENCE_TIMEOUT)
            # Re-vérifier que l'appel est toujours dans un état enregistrement actif
            fresh = await self._get_state(channel_id)
            if fresh and fresh.get("state") in self._ACTIVE_RECORDING_STATES:
                logger.debug(
                    f"[ARI] END_SILENCE_TIMEOUT ({END_SILENCE_TIMEOUT}s) → "
                    f"arrêt enregistrement {recording_name}"
                )
                async with self._client() as c:
                    await c.post(f"/recordings/live/{recording_name}/stop")
            self._end_silence_tasks.pop(channel_id, None)

        # Annule un éventuel timer précédent (ne devrait pas arriver mais sécurité)
        existing = self._end_silence_tasks.pop(channel_id, None)
        if existing:
            existing.cancel()

        task = asyncio.create_task(_stop_after_end_silence())
        self._end_silence_tasks[channel_id] = task

    async def _on_channel_destroyed(self, event: Dict[str, Any]) -> None:
        """Appel non décroché (timeout, busy, rejected) → persistence DB + nettoyage."""
        channel_id = event.get("channel", {}).get("id")
        if not channel_id:
            return
        state = await self._get_state(channel_id)
        # Uniquement si le channel n'a jamais été décroché (StasisStart non déclenché)
        # Si le patient avait décroché, StasisEnd gère la persistence et supprime l'état
        if not state or state.get("state") not in ("initiated", CallState.INITIATED):
            return
        cause = event.get("cause", 0)
        reason = {CAUSE_BUSY: "busy", CAUSE_NO_ANSWER: "no_answer", CAUSE_REJECTED: "call_rejected"}.get(cause, "no_answer")
        logger.info(f"[ARI] Appel sans réponse: {channel_id} | cause Q.850={cause} ({reason})")
        state["state"] = CallState.FAILED
        state["alert_triggered"] = True
        state["alert_type"] = "contact_failure"
        state["alert_reason"] = reason
        asyncio.create_task(self._persist_call(state))
        await self._delete_state(channel_id)

    # ── Originate appel sortant ──────────────────────────────────────────────

    async def originate(
        self,
        phone_number: str,
        patient_id: Optional[str] = None,
        call_db_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Initie un appel sortant vers phone_number via OVH SIP trunk.
        Retourne le channel_id Asterisk ou None si erreur.
        """
        if not self.is_configured:
            logger.error("[ARI] Service non configuré (credentials manquants)")
            return None

        channel_id = uuid.uuid4().hex
        # OVH SIP attend le format 00XXXXXXXXXXX (remplacement de + par 00)
        if phone_number.startswith("+"):
            callee = "00" + phone_number[1:]
        else:
            callee = phone_number

        # Charger les données patient pour interpolation du message d'accueil
        patient_prenom = ""
        patient_nom = ""
        patient_civilite = ""
        patient_service_code = ""
        if patient_id:
            try:
                from app.database import AsyncSessionLocal
                from app.models.patient import Patient as PatientModel
                from sqlalchemy import select as sa_select
                async with AsyncSessionLocal() as _db:
                    _p = await _db.scalar(sa_select(PatientModel).where(PatientModel.id == patient_id))
                    if _p:
                        patient_prenom = _p.prenom or ""
                        patient_nom = _p.nom or ""
                        sexe = (_p.sexe or "").upper()
                        patient_civilite = "Madame" if sexe == "F" else "Monsieur"
                        patient_service_code = _p.service_hospitalisation or ""
            except Exception as _e:
                logger.warning(f"[ARI] Impossible de charger patient {patient_id}: {_e}")

        # Prépare l'état initial dans Redis AVANT l'originate pour éviter
        # la race condition si StasisStart arrive très vite
        initial_state: Dict[str, Any] = {
            "channel_id": channel_id,
            "call_db_id": call_db_id,
            "patient_id": patient_id,
            "patient_prenom": patient_prenom,
            "patient_nom": patient_nom,
            "patient_civilite": patient_civilite,
            "patient_service_code": patient_service_code,
            "caller_role": None,
            "person_check_retry": False,
            "phone_number": phone_number,
            "state": CallState.INITIATED,
            "current_question_index": 0,
            "current_follow_up_index": -1,
            "answers": [],
            "pre_answered": {},
            "alert_triggered": False,
            "retry_count": 0,
            "_needs_skip": False,
            "last_playback_id": None,
            "last_playback_role": None,   # "welcome" | "question" | "ack" | "closing" | "alert"
            "last_recording_name": None,
            "last_tts_file": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._save_state(channel_id, initial_state)

        # Originate via ARI — mode dialplan (pas app= direct)
        # Le dialplan hellojade-outbound exécute AMD() puis Stasis(),
        # ce qui permet de détecter les répondeurs AVANT tout TTS/STT Azure.
        async with self._client() as c:
            r = await c.post(
                "/channels",
                params={
                    "endpoint": f"PJSIP/{callee}@{self.trunk}",
                    "callerId": self.caller_number,
                    "channelId": channel_id,
                    "timeout": 30,
                    "context": "hellojade-outbound",
                    "extension": callee,
                    "priority": 1,
                },
            )

        if r.status_code not in (200, 201):
            logger.error(f"[ARI] Originate failed: {r.status_code} {r.text}")
            await self._delete_state(channel_id)
            return None

        # Pré-synthèse en background des messages qui incluent le prénom/nom du patient.
        # Ces 4 messages sont toujours des cache misses à l'appel TTS (hash ≠ template),
        # donc on les génère pendant la sonnerie (~5 s disponibles).
        if patient_prenom or patient_nom:
            asyncio.create_task(
                self._presynthesize_patient_messages(
                    patient_prenom, patient_nom, initial_state
                )
            )

        logger.info(f"[ARI] Appel initié → {phone_number} (channel: {channel_id})")
        return channel_id

    # ── Handlers d'événements ARI ────────────────────────────────────────────

    async def _call_duration_watchdog(self, channel_id: str, max_minutes: int) -> None:
        """
        Watchdog par appel : raccroche si la durée maximale configurée est dépassée.
        Lancé en background dès que le patient décroche (humain confirmé).
        """
        await asyncio.sleep(max_minutes * 60)
        state = await self._get_state(channel_id)
        if not state:
            return  # Appel déjà terminé normalement
        # Ne pas interrompre un appel déjà en cours de fermeture
        if state.get("state") in (
            CallState.COMPLETED, CallState.FAILED,
            CallState.CLOSING, CallState.TRANSFERRING,
        ):
            return
        logger.info(
            f"[ARI] Durée max atteinte ({max_minutes} min) → raccrochage : {channel_id}"
        )
        state["state"] = CallState.FAILED
        state["alert_triggered"] = True
        state["alert_type"] = "contact_failure"
        state["alert_reason"] = "max_duration_reached"
        await self._save_state(channel_id, state)
        await self._hangup(channel_id)

    async def _on_stasis_start(self, event: Dict[str, Any]) -> None:
        """Patient a décroché → vérifier AMD puis lancer le message de bienvenue."""
        channel = event.get("channel", {})
        channel_id = channel.get("id")
        if not channel_id:
            return

        state = await self._get_state(channel_id)
        if not state:
            logger.warning(f"[ARI] StasisStart sans état Redis: {channel_id}")
            return

        # ── Détection AMD par le dialplan ────────────────────────────────────
        # Le dialplan hellojade-outbound passe UNIQUEID en 2e arg et AMDSTATUS en 3e :
        # args = ["outbound", "<UNIQUEID>", "MACHINE"|"HUMAN"|"NOTSURE"|"HANGUP"]
        stasis_args: List[str] = event.get("args", [])
        asterisk_unique_id = stasis_args[1] if len(stasis_args) > 1 else None
        amd_status = stasis_args[2].upper() if len(stasis_args) > 2 else "NOTSURE"
        logger.info(f"[ARI] Appel décroché: {channel_id} — AMD={amd_status} — UNIQUEID={asterisk_unique_id}")

        if amd_status == "MACHINE":
            cs = await call_settings_service.get()
            amd_behavior = cs.get("amd_behavior", "retry")
            logger.warning(
                f"[ARI] Répondeur détecté par AMD → raccrocher "
                f"(channel: {channel_id}, amd_behavior={amd_behavior})"
            )
            state["_amd_detected"] = True
            state["_amd_behavior"] = amd_behavior  # transmis à _persist_call
            state["state"] = CallState.FAILED
            await self._save_state(channel_id, state)
            await self._hangup(channel_id)
            return
        # ─────────────────────────────────────────────────────────────────────

        # Lancer le watchdog de durée max d'appel en arrière-plan
        cs = await call_settings_service.get()
        max_minutes = int(cs.get("max_call_duration_minutes", 10))
        asyncio.create_task(self._call_duration_watchdog(channel_id, max_minutes))

        await self._hydrate_questionnaire_from_db(state)
        await self._hydrate_messages_from_db(state)
        qnav_check = self._questionnaire(state)
        if len(qnav_check) == 0:
            logger.error("[ARI] Aucune question active — message de clôture et raccrochage")
            tts_file = await self._synthesize(NO_ACTIVE_QUESTIONS_MESSAGE, "no_questions")
            if not tts_file:
                await self._hangup(channel_id)
                return
            playback_id = await self._play(channel_id, f"{ASTERISK_SOUNDS_PREFIX}/{tts_file}")
            if not playback_id:
                self._cleanup_tts(tts_file)
                await self._hangup(channel_id)
                return
            state.update({
                "state": CallState.WELCOME,
                "last_playback_id": playback_id,
                "last_playback_role": "no_questions",
                "last_tts_file": tts_file,
            })
            await self._save_state(channel_id, state)
            return

        # Charger le message d'accueil depuis la DB et interpoler les données patient
        welcome_text = await self._get_welcome_message(state)
        tts_file = await self._synthesize(welcome_text, "welcome")
        if not tts_file:
            await self._hangup(channel_id)
            return

        playback_id = await self._play(channel_id, f"{ASTERISK_SOUNDS_PREFIX}/{tts_file}")
        if not playback_id:
            self._cleanup_tts(tts_file)
            await self._hangup(channel_id)
            return

        state.update({
            "state": CallState.WELCOME,
            "last_playback_id": playback_id,
            "last_playback_role": "welcome",
            "last_tts_file": tts_file,
            "answer_timestamp": time.time(),
            "full_recording_uniqueid": asterisk_unique_id,
        })
        await self._save_state(channel_id, state)
        # Active TALK_DETECT en arrière-plan (non bloquant — AMD)
        asyncio.create_task(self._enable_talk_detect(channel_id))

    async def _on_playback_finished(self, event: Dict[str, Any]) -> None:
        """Un Playback s'est terminé → décider de la prochaine action."""
        playback = event.get("playback", {})
        playback_id = playback.get("id")
        target_uri = playback.get("target_uri", "")  # "channel:CHANNEL_ID"
        channel_id = target_uri.replace("channel:", "") if target_uri.startswith("channel:") else None

        if not channel_id:
            return

        state = await self._get_state(channel_id)
        if not state:
            return

        # Guard : ignorer les events PlaybackFinished obsolètes (arrivée tardive d'un
        # événement pour un playback déjà remplacé par un nouveau).
        if state.get("last_playback_id") and playback_id != state.get("last_playback_id"):
            logger.debug(
                f"[ARI] PlaybackFinished ignoré (stale id={playback_id}, "
                f"attendu={state.get('last_playback_id')})"
            )
            return

        role = state.get("last_playback_role")
        logger.info(f"[ARI] TTS done: role={role} (channel: {channel_id})")
        tts_file = state.get("last_tts_file")

        # Nettoyage du WAV TTS précédent
        if tts_file:
            self._cleanup_tts(tts_file)
            state["last_tts_file"] = None

        if role == "welcome":
            await self._ask_person_check_question(channel_id, state)

        elif role == "person_check_question":
            await self._start_yesno_recording(channel_id, state, prefix="hj_pcheck_")

        elif role == "proche_check_question":
            await self._start_yesno_recording(channel_id, state, prefix="hj_procheck_")

        elif role == "consent_question":
            await self._start_yesno_recording(channel_id, state, prefix="hj_consent_")

        elif role == "person_not_found":
            await self._hangup(channel_id)

        elif role == "consent_refused":
            await self._hangup(channel_id)

        elif role == "question":
            # Démarrer l'enregistrement
            await self._start_recording(channel_id, state)

        elif role == "ack":
            # Re-lire l'état FRAIS depuis Redis avant de sauvegarder le flag :
            # STT+Mistral ont pu avancer les indices entre le début de _on_playback_finished
            # et maintenant — ne pas écraser cet avancement avec le state vieux.
            current = await self._get_state(channel_id)
            if not current:
                return
            current["_ack_ready"] = True
            await self._save_state(channel_id, current)
            fresh = await self._get_state(channel_id)
            if fresh and fresh.get("_stt_ready"):
                await self._after_ack_and_stt(channel_id, fresh)
            return  # Ne pas tomber dans le save final qui écraserait _ack_ready

        elif role in ("retry_prefix_play", "skip_prefix_play", "oob_prefix_play"):
            # Préfixe statique terminé → jouer le texte suivant (statique si dispo, sinon TTS)
            current = await self._get_state(channel_id)
            if not current:
                return
            # Priorité : fichier statique déjà résolu (ex: reprompt statique OOB)
            static_next = current.pop("_pending_question_static", None)
            q_text = current.pop("_pending_question_text", "")
            hint = current.pop("_pending_question_hint", "q_pending")
            if static_next:
                tts_file = static_next
            elif q_text:
                tts_file = await self._synthesize(q_text, hint)
            else:
                logger.warning(f"[ARI] {role}: rien à jouer après le préfixe, skip")
                await self._save_state(channel_id, current)
                return
            if not tts_file:
                await self._hangup(channel_id)
                return
            playback_id = await self._play(channel_id, f"{ASTERISK_SOUNDS_PREFIX}/{tts_file}")
            current.update({
                "state": CallState.QUESTIONING,
                "last_playback_id": playback_id,
                "last_playback_role": "question",
                "last_tts_file": tts_file if not static_next else None,
            })
            await self._save_state(channel_id, current)
            return  # état déjà sauvegardé

        elif role == "alert":
            await self._do_transfer(channel_id, state)

        elif role == "closing":
            await self._hangup(channel_id)

        elif role == "no_questions":
            await self._hangup(channel_id)

        await self._save_state(channel_id, state)

    async def _on_recording_finished(self, event: Dict[str, Any]) -> None:
        """Enregistrement terminé → ack immédiat + STT+Mistral en background."""
        recording = event.get("recording", {})
        recording_name = recording.get("name")
        duration_s = recording.get("duration", "?")
        channel_id = recording.get("target_uri", "").replace("channel:", "")

        if not channel_id or not recording_name:
            return

        logger.info(f"[ARI] RecordingFinished: {recording_name} duration={duration_s}s (channel: {channel_id})")

        state = await self._get_state(channel_id)
        if not state:
            return

        state["last_recording_name"] = recording_name

        # Enregistrements oui/non (person check, proche, consent) → traitement séparé (pas d'ACK)
        if recording_name.startswith("hj_pcheck_"):
            asyncio.create_task(
                self._process_person_check_recording(channel_id, recording_name, state)
            )
            return
        if recording_name.startswith("hj_procheck_"):
            asyncio.create_task(
                self._process_proche_recording(channel_id, recording_name, state)
            )
            return
        if recording_name.startswith("hj_consent_"):
            asyncio.create_task(
                self._process_consent_recording(channel_id, recording_name, state)
            )
            return

        # ── STT + Mistral en background — démarre IMMÉDIATEMENT, en parallèle de l'ACK ─
        asyncio.create_task(
            self._process_recording(channel_id, recording_name, state)
        )

        # ── Sélection du son ACK ──────────────────────────────────────────────
        # Confirmation verbale courte (TTS Azure, anti-repeat sur les 4 dernières)
        recent: list[int] = state.get("recent_acks", [])
        available = [i for i in range(len(ACK_ENTRIES_NEUTRAL)) if i not in recent]
        if not available:
            available = list(range(len(ACK_ENTRIES_NEUTRAL)))
            recent = []
        idx = random.choice(available)
        state["recent_acks"] = (recent + [idx])[-4:]
        ack_text, ack_rate, ack_pitch = ACK_ENTRIES_NEUTRAL[idx]
        ack_ssml = azure_tts_service.build_ssml(ack_text, rate=ack_rate, pitch=ack_pitch)
        ack_file = await self._synthesize(ack_ssml, "ack", use_ssml=True)

        if ack_file:
            playback_id = await self._play(channel_id, f"{ASTERISK_SOUNDS_PREFIX}/{ack_file}")
            state.update({
                "state": CallState.ANALYZING,
                "last_playback_id": playback_id,
                "last_playback_role": "ack",
                "ack_started_at": asyncio.get_event_loop().time(),
                "last_tts_file": ack_file,
            })
            await self._save_state(channel_id, state)
        else:
            # Fallback si TTS échoue : on continue sans ACK
            state.update({"state": CallState.ANALYZING})
            state["_ack_ready"] = True
            await self._save_state(channel_id, state)
            fresh_ack = await self._get_state(channel_id)
            if fresh_ack and fresh_ack.get("_stt_ready"):
                await self._after_ack_and_stt(channel_id, fresh_ack)

    async def _process_recording(
        self,
        channel_id: str,
        recording_name: str,
        state: Dict[str, Any],
    ) -> None:
        """
        Background : Azure STT → Mistral → mise à jour état Redis.
        Exécuté en parallèle de l'ack TTS.
        """
        try:
            # Chemin fichier Asterisk : /var/spool/asterisk/recording/{name}.wav
            recording_path = f"/var/spool/asterisk/recording/{recording_name}.wav"

            # Détecter le contexte médicament sur la question AVANT de lancer le STT
            _q_idx_pre = state.get("current_question_index", 0)
            _fu_idx_pre = state.get("current_follow_up_index", -1)
            _qnav_pre = self._questionnaire(state)
            try:
                _pre_q = (
                    _qnav_pre[_q_idx_pre]["follow_ups"][_fu_idx_pre]
                    if _fu_idx_pre >= 0
                    else _qnav_pre[_q_idx_pre]
                )
                _use_med_ctx = bool(_pre_q.get("medication_context", False))
            except (IndexError, KeyError):
                _use_med_ctx = False

            try:
                with open(recording_path, "rb") as f:
                    audio_bytes = f.read()
                logger.info(f"[ARI] STT submit: {recording_name} size={len(audio_bytes)}B med_ctx={_use_med_ctx} (channel: {channel_id})")
                transcript = await azure_stt_service.transcribe_bytes(
                    audio_bytes, use_medication_context=_use_med_ctx
                )
            except (FileNotFoundError, PermissionError) as e:
                logger.warning(f"[ARI] Recording inaccessible: {recording_path} – {e}")
                transcript = ""
            logger.info(f"[ARI] STT → '{transcript}' (med_ctx={_use_med_ctx}) (channel: {channel_id})")

            # Recharger l'état (peut avoir changé pendant le STT)
            state = await self._get_state(channel_id)
            if not state:
                return

            q_idx = state["current_question_index"]
            fu_idx = state["current_follow_up_index"]
            qnav = self._questionnaire(state)

            if fu_idx >= 0:
                current_q = qnav[q_idx]["follow_ups"][fu_idx]
            else:
                current_q = qnav[q_idx]

            # Formulation de la question selon le rôle de l'interlocuteur
            _caller_role = state.get("caller_role") or "patient"
            _q_text = self._get_question_text(current_q, _caller_role)

            # ── AMD confirmation sur Q1 ───────────────────────────────────────
            # Si TALK_DETECT a signalé un décrochage rapide ET que la transcription
            # de Q1 est vide ou contient un pattern de répondeur → on raccroche.
            if q_idx == 0 and fu_idx < 0 and state.get("_amd_suspect"):
                transcript_lower = transcript.lower()
                _is_machine = not transcript.strip() or any(
                    p in transcript_lower for p in AMD_MACHINE_PATTERNS
                )
                if _is_machine:
                    logger.info(f"[ARI] AMD confirmé — répondeur détecté ('{transcript[:60]}')")
                    state["_amd_detected"] = True
                    await self._save_state(channel_id, state)
                    await self._hangup(channel_id)
                    return

            # Option 1 : transcript vide → traité comme méta-réponse
            _t_lower = transcript.lower().strip()
            _t_words = _t_lower.split()
            is_meta = (
                not transcript.strip()
                or any(kw in _t_lower for kw in _META_RESPONSE_KEYWORDS)
                # Mots seuls déclencheurs uniquement si le transcript est ≤ 3 mots
                # (évite les faux positifs : "pardon de vous déranger, j'ai mal")
                or (len(_t_words) <= 3 and _t_lower.rstrip("?.!,;") in _META_SHORT_WORDS)
            )
            retry_count = state.get("retry_count", 0)

            if is_meta and retry_count < UNCLEAR_MAX_RETRIES:
                # Retry : rejouer la même question
                logger.info(
                    f"[ARI] Transcript méta-réponse (is_meta=True) — "
                    f"relance (essai {retry_count + 1}/{UNCLEAR_MAX_RETRIES}) "
                    f"| transcript='{transcript[:60]}'"
                )
                state["retry_count"] = retry_count + 1
                state["_needs_retry"] = True
                state["_stt_ready"] = True
                await self._save_state(channel_id, state)
                fresh = await self._get_state(channel_id)
                if fresh and fresh.get("_ack_ready"):
                    await self._after_ack_and_stt(channel_id, fresh)
                return

            if is_meta:
                # Option 4 : max retries atteint → skip sans appel Mistral
                logger.info(
                    f"[ARI] Max retry ({UNCLEAR_MAX_RETRIES}) atteint, "
                    f"question {current_q.get('id')} ignorée"
                )
                answer_entry = {
                    "question_id": current_q.get("id", "unknown"),
                    "question": _q_text,
                    "transcript": transcript,
                    "parsed": {
                        "answer": None,
                        "understood": False,
                        "confidence": 0.0,
                        "skipped": True,
                    },
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                state["answers"].append(answer_entry)
                state["retry_count"] = 0
                state["_needs_retry"] = False
                state["_needs_skip"] = True  # Option 3 : annonce avant la question suivante
                self._advance_question(state, {"answer": None})

                # Détection précoce répondeur : si ≥2 questions consécutives
                # entièrement skippées (silence persistant) → messagerie vocale
                _skipped_count = sum(
                    1 for a in state["answers"]
                    if a.get("parsed", {}).get("skipped")
                )
                if _skipped_count >= 2:
                    logger.info(
                        f"[ARI] Messagerie détectée ({_skipped_count} questions sans réponse) "
                        f"— raccrocher immédiatement"
                    )
                    state["_amd_detected"] = True
                    await self._save_state(channel_id, state)
                    await self._hangup(channel_id)
                    return

                # → fall through vers le rendezvous

            else:
                # Fast-path yesno : court-circuit Mistral pour réponses évidentes (~700ms économisé)
                _q_type_now = current_q.get("type", "yesno")
                parsed = _fast_yesno_parse(transcript) if _q_type_now == "yesno" else None
                if parsed:
                    logger.info(
                        f"[ARI] Fast-path yesno: '{transcript[:40]}' → "
                        f"answer={parsed['answer']} (conf={parsed['confidence']})"
                    )
                else:
                    # Parsing Mistral (+ contexte des questions suivantes pour l'anticipation)
                    upcoming_hint, upcoming_qs = self._upcoming_questions_data(state)
                    parsed = await mistral_service.analyze_response(
                        question_id=current_q.get("id", "unknown"),
                        question_text=_q_text,
                        question_type=current_q.get("type", "yesno"),
                        patient_response=transcript,
                        choices=current_q.get("choices"),
                        upcoming_context=upcoming_hint or None,
                        upcoming_questions=upcoming_qs or None,
                        caller_role=_caller_role,
                    )
                parsed = mistral_service.normalize_parsed_response(parsed)
                # Stocker les anticipations dans le state pour _advance_question
                if parsed.get("pre_answered"):
                    state.setdefault("pre_answered", {}).update(parsed["pre_answered"])

                # Politesse pure sans contenu médical : Mistral a mis understood=True
                # mais answer="" pour une question yesno/score/choice.
                # Ex : patient dit "bien compris", "OK merci" → doit relancer la question.
                _q_type = current_q.get("type", "yesno")
                if (
                    parsed.get("understood", True)
                    and not parsed.get("answer")
                    and not parsed.get("out_of_scope")
                    and _q_type not in ("open",)
                    and retry_count < UNCLEAR_MAX_RETRIES
                ):
                    logger.info(
                        f"[ARI] Réponse vide sans contenu médical (type={_q_type}) "
                        f"— relance (essai {retry_count + 1}/{UNCLEAR_MAX_RETRIES})"
                    )
                    state["retry_count"] = retry_count + 1
                    state["_needs_retry"] = True
                    state["_stt_ready"] = True
                    await self._save_state(channel_id, state)
                    fresh = await self._get_state(channel_id)
                    if fresh and fresh.get("_ack_ready"):
                        await self._after_ack_and_stt(channel_id, fresh)
                    return

                # Hors périmètre : message dédié puis même question (sans compter comme retry métier)
                if mistral_service.parsed_is_out_of_scope(parsed):
                    answer_entry = {
                        "question_id": current_q.get("id", "unknown"),
                        "question": _q_text,
                        "transcript": transcript,
                        "parsed": {
                            **parsed,
                            "out_of_scope": True,
                            "understood": True,
                        },
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    state["answers"].append(answer_entry)
                    state["retry_count"] = 0
                    state["_needs_retry"] = False
                    state["_needs_skip"] = False
                    state["_needs_oob"] = True
                    current = await self._get_state(channel_id)
                    if not current:
                        return
                    current["answers"] = state["answers"]
                    current["retry_count"] = 0
                    current["_needs_retry"] = False
                    current["_needs_skip"] = False
                    current["_needs_oob"] = True
                    current["_stt_ready"] = True
                    await self._save_state(channel_id, current)
                    fresh = await self._get_state(channel_id)
                    if fresh and fresh.get("_ack_ready"):
                        await self._after_ack_and_stt(channel_id, fresh)
                    return

                # Option 2 : Mistral n'a pas compris → retry si quota disponible
                if not parsed.get("understood", True) and retry_count < UNCLEAR_MAX_RETRIES:
                    logger.info(
                        f"[ARI] Mistral: réponse non comprise "
                        f"(essai {retry_count + 1}/{UNCLEAR_MAX_RETRIES})"
                    )
                    state["retry_count"] = retry_count + 1
                    state["_needs_retry"] = True
                    state["_stt_ready"] = True
                    await self._save_state(channel_id, state)
                    fresh = await self._get_state(channel_id)
                    if fresh and fresh.get("_ack_ready"):
                        await self._after_ack_and_stt(channel_id, fresh)
                    return

                if not parsed.get("understood", True):
                    logger.info(
                        f"[ARI] Mistral: réponse toujours non comprise après "
                        f"{retry_count} essais, on continue"
                    )

                # Sauvegarder la réponse
                answer_entry = {
                    "question_id": current_q["id"],
                    "question": _q_text,
                    "transcript": transcript,
                    "parsed": parsed,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                state["answers"].append(answer_entry)
                state["retry_count"] = 0
                state["_needs_retry"] = False
                state["_needs_skip"] = False

                # Détection alerte
                alert_if = current_q.get("alert_if")
                alert_conditions = current_q.get("alert_conditions", [])
                alert_if_gte = current_q.get("alert_if_gte")
                if alert_if and parsed.get("answer") == alert_if:
                    state["alert_triggered"] = True
                    if not state.get("alert_type"):
                        q_alert_type = current_q.get("alert_type", "clinical")
                        state["alert_type"] = q_alert_type
                        state["alert_reason"] = current_q.get("id", "")
                if alert_conditions:
                    for cond in alert_conditions:
                        if parsed.get("answer") == cond:
                            state["alert_triggered"] = True
                            if not state.get("alert_type"):
                                state["alert_type"] = current_q.get("alert_type", "clinical")
                                state["alert_reason"] = current_q.get("id", "")
                if alert_if_gte is not None:
                    try:
                        if float(parsed.get("answer") or 0) >= float(alert_if_gte):
                            state["alert_triggered"] = True
                            if not state.get("alert_type"):
                                state["alert_type"] = current_q.get("alert_type", "clinical")
                                state["alert_reason"] = current_q.get("id", "")
                            logger.info(
                                f"[ARI] Alerte score: {current_q.get('id')} = "
                                f"{parsed.get('answer')} >= {alert_if_gte}"
                            )
                    except (ValueError, TypeError):
                        pass

                # Alerte croisée Q2+Q3 : patient ne s'alimente pas (Q2=non)
                # ET n'a ni nausées ni vomissements pour l'expliquer (Q3=non)
                if current_q.get("id") == "Q3_nausees" and parsed.get("answer") == "non":
                    q2_answer = next(
                        (a.get("parsed", {}).get("answer")
                         for a in reversed(state["answers"])
                         if a.get("question_id") == "Q2_alimentation"),
                        None,
                    )
                    if q2_answer == "non" and not state.get("alert_triggered"):
                        state["alert_triggered"] = True
                        state["alert_type"] = "clinical"
                        state["alert_reason"] = "alimentation_non_nausee_non"

                # Avancer l'index de question
                self._advance_question(state, parsed)

            # ── Rendezvous (Bug C fix) : re-lire Redis JUSTE avant de poser _stt_ready,
            # pour ne pas écraser un éventuel _ack_ready posé par _on_playback_finished
            # pendant l'exécution de Mistral (même pattern que le Bug A fix).
            current = await self._get_state(channel_id)
            if not current:
                return
            current["answers"] = state["answers"]
            current["pre_answered"] = state.get("pre_answered", {})
            current["alert_triggered"] = state.get("alert_triggered", current.get("alert_triggered", False))
            current["alert_type"] = state.get("alert_type", current.get("alert_type"))
            current["alert_reason"] = state.get("alert_reason", current.get("alert_reason"))
            current["current_question_index"] = state["current_question_index"]
            current["current_follow_up_index"] = state["current_follow_up_index"]
            current["retry_count"] = state.get("retry_count", 0)
            current["_needs_retry"] = state.get("_needs_retry", False)
            current["_needs_skip"] = state.get("_needs_skip", False)
            current["_stt_ready"] = True
            await self._save_state(channel_id, current)
            fresh = await self._get_state(channel_id)
            if fresh and fresh.get("_ack_ready"):
                await self._after_ack_and_stt(channel_id, fresh)
            elif fresh and fresh.get("last_playback_role") == "ack":
                # Analyse terminée avant la fin du ACK.
                # On attend que l'ACK ait joué au moins ACK_MIN_PLAY_S secondes avant de couper,
                # pour éviter qu'un son soit tronqué au début (ex: "Hm—" au lieu de "Hum hum.").
                pb_id = fresh.get("last_playback_id")
                if pb_id:
                    elapsed = asyncio.get_event_loop().time() - fresh.get("ack_started_at", 0)
                    remaining = max(0.0, ACK_MIN_PLAY_S - elapsed)
                    if remaining > 0:
                        await asyncio.sleep(remaining)
                    logger.info(
                        f"[ARI] ACK court-circuité après {elapsed + remaining:.2f}s "
                        f"(channel: {channel_id})"
                    )
                    await self._stop_playback(channel_id, pb_id)
                    # PlaybackFinished → _on_playback_finished → role="ack" → _ack_ready=True
                    # → lira _stt_ready=True → appellera _after_ack_and_stt

        except Exception as exc:
            logger.error(f"[ARI] Erreur processing recording: {exc}", exc_info=True)

    async def _after_ack_and_stt(self, channel_id: str, state: Dict[str, Any]) -> None:
        """Appelé quand ACK ET STT+Mistral sont tous les deux terminés."""
        logger.info(f"[ARI] ACK+STT ready → next question (channel: {channel_id})")
        state.pop("_ack_ready", None)
        state.pop("_stt_ready", None)
        await self._save_state(channel_id, state)
        if state.pop("_needs_oob", False):
            await self._play_out_of_scope_and_repeat_question(channel_id, state)
            return
        # Alerte / transfert : seulement après la fin du questionnaire (voir _ask_next_question)
        await self._ask_next_question(channel_id, state)

    def _advance_question(self, state: Dict[str, Any], parsed: Dict[str, Any]) -> None:
        """Calcule l'index de la prochaine question (principale ou sous-question).

        Après chaque avance, vérifie si la question suivante figure dans
        state["pre_answered"]. Si oui, enregistre la réponse synthétique,
        déclenche les alertes éventuelles, et avance encore (boucle).
        """
        qnav = self._questionnaire(state)

        def _do_advance(q_idx: int, fu_idx: int, cur_parsed: Dict[str, Any]) -> None:
            current_q = qnav[q_idx]
            follow_ups = current_q.get("follow_ups", [])

            if fu_idx >= 0:
                main_answer = None
                for ans in reversed(state["answers"]):
                    if ans.get("question_id") == current_q["id"]:
                        main_answer = ans.get("parsed", {}).get("answer")
                        break
                next_fu = fu_idx + 1
                while next_fu < len(follow_ups):
                    fu = follow_ups[next_fu]
                    cond = fu.get("condition")
                    if not cond:
                        state["current_follow_up_index"] = next_fu
                        return
                    parent_id = fu.get("condition_parent_id")
                    if parent_id:
                        check_answer = None
                        for ans in reversed(state["answers"]):
                            if ans.get("question_id") == parent_id:
                                check_answer = ans.get("parsed", {}).get("answer")
                                break
                    else:
                        check_answer = main_answer
                    match = (check_answer == cond) if isinstance(cond, str) else (check_answer in cond)
                    if match:
                        state["current_follow_up_index"] = next_fu
                        return
                    next_fu += 1
                state["current_follow_up_index"] = -1
                state["current_question_index"] = q_idx + 1
            else:
                answer = cur_parsed.get("answer")
                for i, fu in enumerate(follow_ups):
                    cond = fu.get("condition")
                    if not cond or answer == cond:
                        state["current_follow_up_index"] = i
                        return
                state["current_question_index"] = q_idx + 1

        _do_advance(state["current_question_index"], state["current_follow_up_index"], parsed)

        # Boucle de skip : si la question suivante a déjà été pré-répondue, l'enregistrer et avancer
        pre_answered: Dict[str, Any] = state.get("pre_answered") or {}
        while pre_answered and state["current_question_index"] < len(qnav):
            qi = state["current_question_index"]
            fj = state["current_follow_up_index"]
            if fj >= 0:
                next_q = qnav[qi]["follow_ups"][fj]
            else:
                next_q = qnav[qi]
            next_id = next_q.get("id", "")
            if next_id not in pre_answered:
                break
            pre_val = pre_answered.pop(next_id)
            logger.info(f"[ARI] {next_id} pré-répondu ('{pre_val}') — skip sans poser")
            pre_parsed: Dict[str, Any] = {
                "answer": pre_val,
                "confidence": 1.0,
                "understood": True,
                "out_of_scope": False,
                "notes": "pré-répondu par anticipation",
                "pre_answered": {},
            }
            state["answers"].append({
                "question_id": next_id,
                "question": next_q["question"],
                "transcript": "",
                "parsed": pre_parsed,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            # Alerte éventuelle sur la question skippée
            alert_if = next_q.get("alert_if")
            if alert_if and pre_val == alert_if:
                state["alert_triggered"] = True
                if not state.get("alert_type"):
                    state["alert_type"] = next_q.get("alert_type", "clinical")
                    state["alert_reason"] = next_q.get("id", "")
            _do_advance(qi, fj, pre_parsed)

    # ── Phase destinataire / proche / consentement ───────────────────────────

    def _interpolate(self, text: str, state: Dict[str, Any]) -> str:
        """Substitue {{prénom}} et {{nom}} dans un texte."""
        return (
            text
            .replace("{{prénom}}", state.get("patient_prenom", ""))
            .replace("{{nom}}", state.get("patient_nom", ""))
        )

    async def _ask_person_check_question(self, channel_id: str, state: Dict[str, Any]) -> None:
        """Joue 'Êtes-vous bien [prénom] [nom] ?' (avec retry si déjà tenté)."""
        if state.get("person_check_retry"):
            text = self._interpolate(PERSON_CHECK_RETRY, state)
            hint = "person_check_retry"
        else:
            text = self._interpolate(PERSON_CHECK_QUESTION, state)
            hint = "person_check_q"
        tts_file = await self._synthesize(text, hint)
        if not tts_file:
            # En cas d'échec TTS on passe directement au consentement
            await self._ask_consent_question(channel_id, state)
            return
        playback_id = await self._play(channel_id, f"{ASTERISK_SOUNDS_PREFIX}/{tts_file}")
        if not playback_id:
            self._cleanup_tts(tts_file)
            await self._ask_consent_question(channel_id, state)
            return
        state.update({
            "state": CallState.RECIPIENT_CHECK,
            "last_playback_id": playback_id,
            "last_playback_role": "person_check_question",
            "last_tts_file": tts_file,
        })
        await self._save_state(channel_id, state)

    async def _start_yesno_recording(
        self, channel_id: str, state: Dict[str, Any], prefix: str
    ) -> None:
        """Lance un enregistrement court pour une réponse oui/non."""
        recording_name = f"{prefix}{channel_id[:12]}_{int(time.time())}"
        ok = await self._record(channel_id, recording_name, IDENTITY_YESNO_RECORD_DURATION)
        if ok:
            state["last_recording_name"] = recording_name
            await self._save_state(channel_id, state)
        else:
            # En cas d'échec d'enregistrement, on donne le bénéfice du doute
            await self._ask_consent_question(channel_id, state)

    async def _process_person_check_recording(
        self, channel_id: str, recording_name: str, state: Dict[str, Any]
    ) -> None:
        """Background : STT → oui/non → enchaîne sur proche ou consentement."""
        try:
            transcript = await self._stt_from_recording(recording_name)
            logger.info(f"[ARI] PersonCheck STT → '{transcript}' (channel={channel_id})")

            state = await self._get_state(channel_id)
            if not state:
                return

            answer = _detect_yesno(transcript)

            if answer is True:
                state["caller_role"] = "patient"
                await self._save_state(channel_id, state)
                await self._ask_consent_question(channel_id, state)
            elif answer is False:
                await self._save_state(channel_id, state)
                await self._ask_proche_question(channel_id, state)
            else:
                # Incompréhensible — un seul retry, puis bénéfice du doute (patient)
                if not state.get("person_check_retry"):
                    state["person_check_retry"] = True
                    await self._save_state(channel_id, state)
                    await self._ask_person_check_question(channel_id, state)
                else:
                    logger.info(f"[ARI] PersonCheck incompréhensible après retry — suppose patient (channel={channel_id})")
                    state["caller_role"] = "patient"
                    await self._save_state(channel_id, state)
                    await self._ask_consent_question(channel_id, state)

        except Exception as exc:
            logger.error(f"[ARI] _process_person_check_recording error: {exc}", exc_info=True)
            state = await self._get_state(channel_id)
            if state:
                state["caller_role"] = "patient"
                await self._save_state(channel_id, state)
                await self._ask_consent_question(channel_id, state)

    async def _ask_proche_question(self, channel_id: str, state: Dict[str, Any]) -> None:
        """Joue 'Êtes-vous un proche de [prénom] [nom] ?'."""
        text = self._interpolate(PROCHE_QUESTION, state)
        tts_file = await self._synthesize(text, "proche_q")
        if not tts_file:
            await self._ask_consent_question(channel_id, state)
            return
        playback_id = await self._play(channel_id, f"{ASTERISK_SOUNDS_PREFIX}/{tts_file}")
        if not playback_id:
            self._cleanup_tts(tts_file)
            await self._ask_consent_question(channel_id, state)
            return
        state.update({
            "state": CallState.PROCHE_CHECK,
            "last_playback_id": playback_id,
            "last_playback_role": "proche_check_question",
            "last_tts_file": tts_file,
        })
        await self._save_state(channel_id, state)

    async def _process_proche_recording(
        self, channel_id: str, recording_name: str, state: Dict[str, Any]
    ) -> None:
        """Background : STT → oui (proche) / non (mauvais numéro) → enchaîne."""
        try:
            transcript = await self._stt_from_recording(recording_name)
            logger.info(f"[ARI] ProcheCheck STT → '{transcript}' (channel={channel_id})")

            state = await self._get_state(channel_id)
            if not state:
                return

            answer = _detect_yesno(transcript)

            if answer is False:
                await self._save_state(channel_id, state)
                await self._play_person_not_found(channel_id, state)
            else:
                # oui ou incompréhensible → bénéfice du doute (proche)
                state["caller_role"] = "proche"
                await self._save_state(channel_id, state)
                await self._ask_consent_question(channel_id, state)

        except Exception as exc:
            logger.error(f"[ARI] _process_proche_recording error: {exc}", exc_info=True)
            state = await self._get_state(channel_id)
            if state:
                state["caller_role"] = "proche"
                await self._save_state(channel_id, state)
                await self._ask_consent_question(channel_id, state)

    async def _ask_consent_question(self, channel_id: str, state: Dict[str, Any]) -> None:
        """Joue 'Avez-vous quelques minutes pour répondre à quelques questions ?'."""
        is_proche = state.get("caller_role") == "proche"
        if is_proche:
            text = self._interpolate(CONSENT_QUESTION_PROCHE, state)
            hint = "consent_q_proche"
        else:
            text = CONSENT_QUESTION
            hint = "consent_q"
        tts_file = await self._synthesize(text, hint)
        if not tts_file:
            await self._ask_next_question(channel_id, state)
            return
        playback_id = await self._play(channel_id, f"{ASTERISK_SOUNDS_PREFIX}/{tts_file}")
        if not playback_id:
            self._cleanup_tts(tts_file)
            await self._ask_next_question(channel_id, state)
            return
        state.update({
            "state": CallState.CONSENT_CHECK,
            "last_playback_id": playback_id,
            "last_playback_role": "consent_question",
            "last_tts_file": tts_file,
        })
        await self._save_state(channel_id, state)

    async def _process_consent_recording(
        self, channel_id: str, recording_name: str, state: Dict[str, Any]
    ) -> None:
        """Background : STT → oui → questionnaire / non → raccrochage poli."""
        try:
            transcript = await self._stt_from_recording(recording_name)
            logger.info(f"[ARI] Consent STT → '{transcript}' (channel={channel_id})")

            state = await self._get_state(channel_id)
            if not state:
                return

            answer = _detect_yesno(transcript)

            if answer is False:
                await self._save_state(channel_id, state)
                await self._play_consent_refused(channel_id, state)
            else:
                # oui ou incompréhensible → on continue (bénéfice du doute)
                await self._save_state(channel_id, state)
                await self._ask_next_question(channel_id, state)

        except Exception as exc:
            logger.error(f"[ARI] _process_consent_recording error: {exc}", exc_info=True)
            state = await self._get_state(channel_id)
            if state:
                await self._ask_next_question(channel_id, state)

    async def _play_person_not_found(self, channel_id: str, state: Dict[str, Any]) -> None:
        """Joue le message 'mauvais numéro' puis raccroche."""
        tts_file = await self._synthesize(PERSON_NOT_FOUND_MESSAGE, "person_not_found")
        if not tts_file:
            await self._hangup(channel_id)
            return
        playback_id = await self._play(channel_id, f"{ASTERISK_SOUNDS_PREFIX}/{tts_file}")
        if not playback_id:
            self._cleanup_tts(tts_file)
            await self._hangup(channel_id)
            return
        state.update({
            "state": CallState.CLOSING,
            "last_playback_id": playback_id,
            "last_playback_role": "person_not_found",
            "last_tts_file": tts_file,
        })
        await self._save_state(channel_id, state)

    async def _play_consent_refused(self, channel_id: str, state: Dict[str, Any]) -> None:
        """Joue le message de refus de consentement puis raccroche."""
        tts_file = await self._synthesize(CONSENT_REFUSED_MESSAGE, "consent_refused")
        if not tts_file:
            await self._hangup(channel_id)
            return
        playback_id = await self._play(channel_id, f"{ASTERISK_SOUNDS_PREFIX}/{tts_file}")
        if not playback_id:
            self._cleanup_tts(tts_file)
            await self._hangup(channel_id)
            return
        state.update({
            "state": CallState.CLOSING,
            "last_playback_id": playback_id,
            "last_playback_role": "consent_refused",
            "last_tts_file": tts_file,
        })
        await self._save_state(channel_id, state)

    @staticmethod
    def _get_question_text(q_data: Dict[str, Any], caller_role: str) -> str:
        """Retourne la formulation appropriée selon le rôle de l'interlocuteur."""
        if caller_role == "proche" and q_data.get("question_proche"):
            return q_data["question_proche"]
        return q_data["question"]

    async def _ask_next_question(self, channel_id: str, state: Dict[str, Any]) -> None:
        """Joue la prochaine question TTS ou ferme l'appel si toutes répondues."""
        qnav = self._questionnaire(state)
        q_idx = state["current_question_index"]
        fu_idx = state["current_follow_up_index"]

        needs_retry = state.pop("_needs_retry", False)
        needs_skip = state.pop("_needs_skip", False)
        logger.info(f"[ARI] Next question: q={q_idx} fu={fu_idx} retry={needs_retry} skip={needs_skip} (channel: {channel_id})")

        if not needs_retry and q_idx >= len(qnav):
            # Fin du questionnaire : transfert si alerte clinique / demande patient, sinon clôture standard
            if state.get("alert_triggered"):
                await self._play_alert(channel_id, state)
            else:
                await self._play_closing(channel_id, state)
            return

        _ORDINALS = [
            "Première question :", "Deuxième question :", "Troisième question :",
            "Quatrième question :", "Cinquième question :", "Sixième question :",
            "Septième question :", "Huitième question :", "Neuvième question :",
            "Dixième question :",
        ]

        caller_role = state.get("caller_role") or "patient"

        if fu_idx >= 0:
            q_data = qnav[q_idx]["follow_ups"][fu_idx]
            q_text = self._get_question_text(q_data, caller_role)
            hint = f"q{q_idx}_fu{fu_idx}"
            if caller_role == "proche":
                hint += "_proche"
        else:
            q_data = qnav[q_idx]
            q_text = self._get_question_text(q_data, caller_role)
            hint = f"q{q_idx}"
            if caller_role == "proche":
                hint += "_proche"
            # Préfixe ordinal uniquement sur les questions principales (pas les sous-questions)
            if not needs_retry and 0 <= q_idx < len(_ORDINALS):
                q_text = _ORDINALS[q_idx] + " " + q_text

        # Option 5 : prefix "Je répète." avant la question (fichier statique si dispo)
        if needs_retry:
            static_prefix = self._static("retry_prefix")
            if static_prefix:
                # Jouer le prefix statique d'abord, puis la question sera jouée après
                playback_id = await self._play(channel_id, f"{ASTERISK_SOUNDS_PREFIX}/{static_prefix}")
                state.update({
                    "state": CallState.QUESTIONING,
                    "last_playback_id": playback_id,
                    "last_playback_role": "retry_prefix_play",
                    "last_tts_file": None,
                    "_pending_question_text": q_text,
                    "_pending_question_hint": hint,
                })
                await self._save_state(channel_id, state)
                return
            else:
                q_text = random.choice(RETRY_PREFIXES) + " " + q_text
                hint += "_retry"

        # Option 3 : annonce "Je passe à la suite." avant la question suivante
        elif needs_skip:
            static_skip = self._static("skip")
            if static_skip:
                playback_id = await self._play(channel_id, f"{ASTERISK_SOUNDS_PREFIX}/{static_skip}")
                state.update({
                    "state": CallState.QUESTIONING,
                    "last_playback_id": playback_id,
                    "last_playback_role": "skip_prefix_play",
                    "last_tts_file": None,
                    "_pending_question_text": q_text,
                    "_pending_question_hint": hint,
                })
                await self._save_state(channel_id, state)
                return
            else:
                q_text = SKIP_MESSAGE + " " + q_text
                hint += "_skip"

        tts_file = await self._synthesize(q_text, hint)
        if not tts_file:
            await self._hangup(channel_id)
            return

        playback_id = await self._play(channel_id, f"{ASTERISK_SOUNDS_PREFIX}/{tts_file}")
        state.update({
            "state": CallState.QUESTIONING,
            "last_playback_id": playback_id,
            "last_playback_role": "question",
            "last_tts_file": tts_file,
        })
        await self._save_state(channel_id, state)

    def _upcoming_questions_data(
        self, state: Dict[str, Any]
    ) -> tuple:
        """
        Retourne (hint_str, upcoming_list) pour le LLM.
        - hint_str : texte résumant les prochaines questions (contexte général)
        - upcoming_list : liste de dicts {id, text, type} (pour pre_answered)
        """
        qnav = self._questionnaire(state)
        qi = state.get("current_question_index", 0)
        fj = state.get("current_follow_up_index", -1)
        entries: List[Dict[str, Any]] = []
        if qi >= len(qnav):
            return "", []
        if fj >= 0:
            fus = qnav[qi].get("follow_ups", [])
            for k in range(fj + 1, min(fj + 4, len(fus))):
                q = fus[k]
                t = (q.get("question") or "")[:100].strip()
                if t:
                    entries.append({"id": q.get("id", ""), "text": t, "type": q.get("type", "yesno")})
            for mi in range(qi + 1, min(qi + 3, len(qnav))):
                q = qnav[mi]
                t = (q.get("question") or "")[:100].strip()
                if t:
                    entries.append({"id": q.get("id", ""), "text": t, "type": q.get("type", "yesno")})
        else:
            fus = qnav[qi].get("follow_ups", [])
            for q in fus[:3]:
                t = (q.get("question") or "")[:100].strip()
                if t:
                    entries.append({"id": q.get("id", ""), "text": t, "type": q.get("type", "yesno")})
            for mi in range(qi + 1, min(qi + 2, len(qnav))):
                q = qnav[mi]
                t = (q.get("question") or "")[:100].strip()
                if t:
                    entries.append({"id": q.get("id", ""), "text": t, "type": q.get("type", "yesno")})
        if not entries:
            return "", []
        hint = (
            "Prochaines questions du questionnaire (ne pas y répondre tant qu'elles ne sont pas posées) : "
            + " · ".join(e["text"] for e in entries)
        )
        return hint, entries

    async def _play_out_of_scope_and_repeat_question(
        self, channel_id: str, state: Dict[str, Any]
    ) -> None:
        """Après hors périmètre : static out_of_scope + reprompt statique selon le type de question."""
        qnav = self._questionnaire(state)
        q_idx = state["current_question_index"]
        fu_idx = state["current_follow_up_index"]
        if fu_idx >= 0:
            q_data = qnav[q_idx]["follow_ups"][fu_idx]
            hint = f"oob_reprompt_q{q_idx}_fu{fu_idx}"
        else:
            q_data = qnav[q_idx]
            hint = f"oob_reprompt_q{q_idx}"
        qtype = q_data.get("type", "yesno")
        choices = q_data.get("choices")

        # Reprompt statique selon le type (yesno / score / open) — None pour type choice
        reprompt_key = f"reprompt_{qtype}" if qtype in ("yesno", "score", "open") else None
        reprompt_static = self._static(reprompt_key) if reprompt_key else None

        # Essayer la chaîne statique : out_of_scope → reprompt
        oob_static = self._static("out_of_scope")
        if oob_static:
            tail_text = short_reprompt_after_out_of_scope(qtype, choices)
            # Chaîne statique : out_of_scope → reprompt (statique si dispo, sinon TTS)
            pending: Dict[str, Any] = {
                "state": CallState.QUESTIONING,
                "last_playback_role": "oob_prefix_play",
                "last_tts_file": None,
                "_pending_question_hint": hint,
            }
            if reprompt_static:
                # Reprompt pré-généré (yesno / score / open)
                pending["_pending_question_static"] = reprompt_static
            else:
                # Type choice : reprompt dynamique
                pending["_pending_question_text"] = tail_text
            playback_id = await self._play(channel_id, f"{ASTERISK_SOUNDS_PREFIX}/{oob_static}")
            pending["last_playback_id"] = playback_id
            state.update(pending)
            await self._save_state(channel_id, state)
            return

        # Fallback : tout en un seul TTS (ancien comportement)
        tail = short_reprompt_after_out_of_scope(qtype, choices)
        full_text = f"{OUT_OF_SCOPE_MESSAGE}{tail}"
        tts_file = await self._synthesize(full_text, hint)
        if not tts_file:
            await self._hangup(channel_id)
            return
        playback_id = await self._play(channel_id, f"{ASTERISK_SOUNDS_PREFIX}/{tts_file}")
        state.update({
            "state": CallState.QUESTIONING,
            "last_playback_id": playback_id,
            "last_playback_role": "question",
            "last_tts_file": tts_file,
        })
        await self._save_state(channel_id, state)

    async def _start_recording(self, channel_id: str, state: Dict[str, Any]) -> None:
        """Lance l'enregistrement de la réponse du patient."""
        qnav = self._questionnaire(state)
        q_idx = state["current_question_index"]
        fu_idx = state["current_follow_up_index"]

        if fu_idx >= 0:
            q_data = qnav[q_idx]["follow_ups"][fu_idx]
        else:
            q_data = qnav[q_idx]

        max_duration = q_data.get("record_duration", RECORD_DURATION_SHORT)
        recording_name = f"hj_{channel_id[:12]}_{q_idx}_{fu_idx}_{int(time.time())}"

        ok = await self._record(channel_id, recording_name, max_duration)
        if ok:
            state.update({
                "state": CallState.RECORDING,
                "last_recording_name": recording_name,
            })
        else:
            await self._hangup(channel_id)

    async def _play_alert(self, channel_id: str, state: Dict[str, Any]) -> None:
        tts_file = await self._synthesize(self._get_message(state, "outro_alert", CLOSING_MESSAGE_ALERT), "alert")
        if not tts_file:
            await self._hangup(channel_id)
            return
        playback_id = await self._play(channel_id, f"{ASTERISK_SOUNDS_PREFIX}/{tts_file}")
        state.update({
            "state": CallState.ALERT_DETECTED,
            "last_playback_id": playback_id,
            "last_playback_role": "alert",
            "last_tts_file": tts_file,
        })
        await self._save_state(channel_id, state)

    async def _play_closing(self, channel_id: str, state: Dict[str, Any]) -> None:
        db_text = self._get_message(state, "outro_normal", "")
        if db_text:
            closing_text = db_text
        elif state.get("caller_role") == "proche":
            closing_text = CLOSING_MESSAGE_NORMAL_PROCHE
        else:
            closing_text = CLOSING_MESSAGE_NORMAL
        tts_file = await self._synthesize(closing_text, "closing")
        if not tts_file:
            await self._hangup(channel_id)
            return
        playback_id = await self._play(channel_id, f"{ASTERISK_SOUNDS_PREFIX}/{tts_file}")
        state.update({
            "state": CallState.CLOSING,
            "last_playback_id": playback_id,
            "last_playback_role": "closing",
            "last_tts_file": tts_file,
        })
        await self._save_state(channel_id, state)

    async def _do_transfer(self, channel_id: str, state: Dict[str, Any]) -> None:
        """Transfère l'appel vers l'équipe infirmières."""
        transfer_number = settings.TRANSFER_NUMBER
        transfer_mode = settings.TRANSFER_MODE

        if transfer_mode == "disabled" or not transfer_number:
            logger.info(f"[ARI] Transfert désactivé ou numéro manquant")
            await self._play_closing_failed(channel_id, state)
            return

        if transfer_mode == "simulate":
            logger.info(f"[ARI] Transfert simulé vers {transfer_number}")
            await self._play_closing_failed(channel_id, state)
            return

        state["state"] = CallState.TRANSFERRING
        await self._save_state(channel_id, state)
        # Format E.164 → 00XXXXXXXXX pour trunk OVH
        callee = "00" + transfer_number[1:] if transfer_number.startswith("+") else transfer_number
        ok = await self._continue_transfer(channel_id, callee)
        if not ok:
            logger.error(f"[ARI] Transfert échoué vers {transfer_number}")
            await self._play_closing_failed(channel_id, state)

    async def _play_closing_failed(self, channel_id: str, state: Dict[str, Any]) -> None:
        db_text = self._get_message(state, "outro_transfer_failed", "")
        if db_text:
            failed_text = db_text
        elif state.get("caller_role") == "proche":
            failed_text = CLOSING_MESSAGE_TRANSFER_FAILED_PROCHE
        else:
            failed_text = CLOSING_MESSAGE_TRANSFER_FAILED
        tts_file = await self._synthesize(failed_text, "closing_failed")
        if not tts_file:
            await self._hangup(channel_id)
            return
        playback_id = await self._play(channel_id, f"{ASTERISK_SOUNDS_PREFIX}/{tts_file}")
        state.update({
            "state": CallState.CLOSING,
            "last_playback_id": playback_id,
            "last_playback_role": "closing",
            "last_tts_file": tts_file,
        })
        await self._save_state(channel_id, state)

    async def _on_stasis_end(self, event: Dict[str, Any]) -> None:
        """Appel raccroché → persistence DB + nettoyage Redis."""
        channel = event.get("channel", {})
        channel_id = channel.get("id")
        if not channel_id:
            return

        state = await self._get_state(channel_id)
        if not state:
            return

        logger.info(
            f"[ARI] Appel terminé: {channel_id} | "
            f"état: {state.get('state')} | "
            f"réponses: {len(state.get('answers', []))} | "
            f"alerte: {state.get('alert_triggered')}"
        )

        # Annule le timer END_SILENCE s'il est encore actif
        task = self._end_silence_tasks.pop(channel_id, None)
        if task:
            task.cancel()

        # Persistence DB en background (import local pour éviter les cycles)
        asyncio.create_task(self._persist_call(state))
        await self._delete_state(channel_id)

    async def _persist_call(self, state: Dict[str, Any]) -> None:
        """Sauvegarde les résultats de l'appel en base de données."""
        try:
            from app.database import AsyncSessionLocal
            from app.models.call import Call
            from sqlalchemy import select

            call_db_id = state.get("call_db_id")
            if not call_db_id:
                logger.debug("[ARI] Pas de call_db_id → pas de persistence DB")
                return

            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Call).where(Call.id == call_db_id))
                call = result.scalar_one_or_none()
                if not call:
                    return

                # Mapper les états ARI vers les valeurs enum DB valides.
                # _persist_call n'est appelé que sur StasisEnd/ChannelDestroyed → l'appel
                # est terminé. Les états mid-call deviennent "interrupted" (patient a raccroché).
                _state_map = {
                    CallState.COMPLETED: "completed",
                    CallState.FAILED: "failed",
                    CallState.RINGING: "ringing",
                    CallState.ANSWERED: "interrupted",
                    CallState.WELCOME: "interrupted",
                    CallState.RECIPIENT_CHECK: "interrupted",
                    CallState.PROCHE_CHECK: "interrupted",
                    CallState.CONSENT_CHECK: "interrupted",
                    CallState.QUESTIONING: "interrupted",
                    CallState.RECORDING: "interrupted",
                    CallState.ANALYZING: "interrupted",
                    CallState.ALERT_DETECTED: "completed",
                    CallState.TRANSFERRING: "completed",
                    CallState.CLOSING: "completed",
                    CallState.INITIATED: "pending",
                }
                ari_state = state.get("state")
                call.status = _state_map.get(ari_state, "completed")
                # Affiner le statut DB pour les appels sans réponse
                _reason_raw = state.get("alert_reason", "")
                if _reason_raw == "busy":
                    call.status = "busy"
                elif _reason_raw in ("no_answer", "call_rejected", "answering_machine"):
                    call.status = "no_answer"
                call.end_time = datetime.now(timezone.utc)
                if call.start_time:
                    call.duration = int(
                        (call.end_time - call.start_time).total_seconds()
                    )
                answers = state.get("answers", [])
                alert_triggered = state.get("alert_triggered", False)
                alert_type = state.get("alert_type")
                alert_reason = state.get("alert_reason")

                # Cas 0 : répondeur détecté (AMD — TALK_DETECT + STT, ou silence persistant)
                _all_skipped = answers and all(
                    a.get("parsed", {}).get("skipped") for a in answers
                )
                if state.get("_amd_detected") or _all_skipped:
                    alert_triggered = True
                    alert_type = "contact_failure"
                    alert_reason = "answering_machine"
                # Cas 1 : zéro réponse collectée → échec identité ou patient non évaluable
                elif not answers:
                    alert_triggered = True
                    alert_type = "contact_failure"
                    alert_reason = "identity_failed" if state.get("_identity_failed") else "no_response"
                # Cas 2 : questionnaire interrompu avant complétion
                elif not alert_triggered:
                    _incomplete_states = {
                        "ringing", "answered", "welcome",
                        "recipient_check", "identity_check",
                        "questioning", "recording", "analyzing",
                    }
                    if ari_state in _incomplete_states:
                        alert_triggered = True
                        alert_type = "contact_failure"
                        alert_reason = "call_interrupted"
                # Cas 3 : transfert demandé mais service non joignable
                elif alert_type == "transfer" and ari_state != "transferring":
                    alert_type = "contact_failure"
                    alert_reason = "transfer_failed"

                alert_symptom_detail = _extract_q6_symptom_detail(answers)

                call.call_metadata = {
                    "answers": answers,
                    "alert_triggered": alert_triggered,
                    "alert_type": alert_type,
                    "alert_reason": alert_reason,
                    "alert_symptom_detail": alert_symptom_detail,
                    "provider": "asterisk_ari",
                    "identity_verified": state.get("identity_verified"),
                    "identity_attempts": state.get("identity_attempts"),
                    "caller_role": state.get("caller_role") or "patient",
                }

                # Commit principal : status + metadata toujours sauvegardés
                await db.commit()
                logger.info(f"[ARI] Call {call_db_id} persisté en DB")

                # ── Mise à jour statut patient + logique de retry ────────────
                patient_id = state.get("patient_id")
                if patient_id:
                    from app.models.patient import Patient
                    from sqlalchemy import func as sa_func
                    patient = await db.get(Patient, patient_id)
                    if patient:
                        patient.last_call_at = call.end_time

                        if alert_type != "contact_failure":
                            # Appel réussi (complété ou alerte clinique) → pas de retry
                            patient.status = "actif"
                            patient.next_call_scheduled = None
                            logger.info(f"[ARI] Patient {patient_id} → actif, prochain appel annulé")
                        elif patient.manually_recalled:
                            # Rappelé manuellement → pas de retry automatique
                            patient.next_call_scheduled = None
                            logger.info(
                                f"[ARI] Patient {patient_id} rappelé manuellement — retry annulé"
                            )
                        else:
                            # Échec de contact → décider s'il faut réessayer
                            cs = await call_settings_service.get()
                            max_attempts = int(cs.get("max_attempts", 3))
                            retry_delay_hours = int(cs.get("retry_delay_hours", 4))
                            amd_behavior = (
                                state.get("_amd_behavior")
                                or cs.get("amd_behavior", "retry")
                            )

                            # Compter les tentatives échouées (y compris celle-ci, déjà commitée)
                            failed_count_result = await db.execute(
                                select(sa_func.count(Call.id)).where(
                                    Call.patient_id == patient_id,
                                    Call.status.in_(["failed", "no_answer", "busy"]),
                                )
                            )
                            failed_count = failed_count_result.scalar() or 0

                            is_answering_machine = alert_reason == "answering_machine"
                            skip_due_to_amd = is_answering_machine and amd_behavior == "skip"
                            is_identity_failed = alert_reason == "identity_failed"

                            if failed_count < max_attempts and not skip_due_to_amd and not is_identity_failed:
                                next_call = datetime.now(timezone.utc) + timedelta(hours=retry_delay_hours)
                                next_call = next_valid_window(next_call, cs)
                                patient.next_call_scheduled = next_call
                                logger.info(
                                    f"[ARI] Retry planifié: patient={patient_id} "
                                    f"→ {next_call.isoformat()} "
                                    f"(tentative {failed_count}/{max_attempts})"
                                )
                            else:
                                patient.next_call_scheduled = None
                                logger.info(
                                    f"[ARI] Aucun retry: patient={patient_id} "
                                    f"(attempts={failed_count}/{max_attempts}, "
                                    f"skip_amd={skip_due_to_amd})"
                                )

                        await db.commit()
                        logger.info(f"[ARI] Patient {patient_id} mis à jour")

                # ── Enregistrement audio complet (non-bloquant) ─────────────
                full_recording_uniqueid = state.get("full_recording_uniqueid")
                if full_recording_uniqueid:
                    src = Path(f"/var/spool/asterisk/recording/calls/full_{full_recording_uniqueid}.wav")
                    if src.exists():
                        patient_id = state.get("patient_id") or "inconnu"
                        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
                        dest_dir = Path(f"/var/spool/asterisk/recording/calls/{patient_id}")
                        dest_dir.mkdir(parents=True, exist_ok=True)
                        dest = dest_dir / f"{date_str}_{call_db_id}.wav"
                        try:
                            shutil.move(str(src), str(dest))
                            call.recording_path = str(dest)
                            call.recording_size = dest.stat().st_size
                            await db.commit()
                            logger.info(f"[ARI] Enregistrement sauvegardé → {dest} ({call.recording_size} octets)")
                        except Exception as exc:
                            logger.warning(f"[ARI] Impossible de déplacer l'enregistrement: {exc}")
                    else:
                        logger.debug(f"[ARI] Fichier MixMonitor absent (AMD/no-answer): {src}")

                # ── Génération PDF ORU en arrière-plan ──────────────────────
                try:
                    from app.tasks.report_tasks import generate_report_async
                    generate_report_async.delay(str(call_db_id))
                    logger.info(f"[ARI] Génération PDF ORU planifiée — call={call_db_id}")
                except Exception as exc:
                    logger.warning(f"[ARI] Impossible de planifier la génération PDF: {exc}")

        except Exception as exc:
            logger.error(f"[ARI] Erreur persistence DB: {exc}", exc_info=True)

    # ── WebSocket — boucle d'événements ARI ──────────────────────────────────

    async def _dispatch_event(self, event: Dict[str, Any]) -> None:
        """Dispatch un événement ARI vers le bon handler."""
        event_type = event.get("type")
        app = event.get("application")

        # ChannelDestroyed : bypass du filtre app car le channel n'entre jamais
        # dans Stasis pour les appels non-décrochés (StasisStart jamais déclenché)
        if event_type == "ChannelDestroyed":
            try:
                await self._on_channel_destroyed(event)
            except Exception as exc:
                logger.error(f"[ARI] Erreur handler ChannelDestroyed: {exc}", exc_info=True)
            return

        if app != self.app_name:
            return

        handlers = {
            "StasisStart": self._on_stasis_start,
            "PlaybackFinished": self._on_playback_finished,
            "RecordingFinished": self._on_recording_finished,
            "StasisEnd": self._on_stasis_end,
            "ChannelTalkingStarted": self._on_channel_talking_started,
            "ChannelTalkingFinished": self._on_channel_talking_finished,
        }

        handler = handlers.get(event_type)
        if handler:
            try:
                await handler(event)
            except Exception as exc:
                logger.error(
                    f"[ARI] Erreur handler {event_type}: {exc}", exc_info=True
                )

    async def _ws_loop(self) -> None:
        """Boucle WebSocket persistante avec reconnexion automatique."""
        ws_url = (
            f"ws://{self.base_url.replace('http://', '').replace('https://', '')}"
            f"/ari/events"
            f"?api_key={self.ari_user}:{self.ari_password}"
            f"&app={self.app_name}"
            f"&subscribeAll=true"
        )

        while True:
            try:
                logger.info("[ARI] Connexion WebSocket Asterisk...")
                async with websockets.connect(ws_url, ping_interval=30) as ws:
                    logger.info("[ARI] WebSocket connecté")
                    async for raw in ws:
                        try:
                            event = json.loads(raw)
                            await self._dispatch_event(event)
                        except json.JSONDecodeError:
                            pass
            except (ConnectionClosedOK, ConnectionClosedError) as exc:
                logger.warning(f"[ARI] WebSocket fermé: {exc} — reconnexion dans 5s")
                await asyncio.sleep(5)
            except Exception as exc:
                logger.error(f"[ARI] WebSocket erreur: {exc} — reconnexion dans 10s")
                await asyncio.sleep(10)

    def start_ws_listener(self) -> None:
        """Lance la boucle WebSocket dans l'event loop FastAPI (à appeler au startup)."""
        if self._ws_task and not self._ws_task.done():
            return
        self._ws_task = asyncio.create_task(self._ws_loop())
        asyncio.create_task(self._stale_calls_watchdog())
        # Pré-synthétise tous les textes statiques en arrière-plan
        asyncio.create_task(self.warm_up_tts_cache())
        logger.info("[ARI] Listener WebSocket démarré")

    async def _stale_calls_watchdog(self) -> None:
        """Watchdog toutes les 5 min : marque 'interrupted' les appels bloqués > 30 min en DB."""
        INTERVAL_S = 300       # vérification toutes les 5 minutes
        STALE_AFTER_MIN = 30   # appel considéré bloqué après 30 minutes sans fin
        await asyncio.sleep(60)  # attendre 1 min après démarrage avant le 1er passage
        while True:
            try:
                from app.database import AsyncSessionLocal
                from app.models.call import Call
                from sqlalchemy import select, update
                cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_AFTER_MIN)
                async with AsyncSessionLocal() as db:
                    result = await db.execute(
                        select(Call.id).where(
                            Call.status.in_(["in_progress", "ringing"]),
                            Call.start_time < cutoff,
                        )
                    )
                    stale_ids = [row[0] for row in result.fetchall()]
                    if stale_ids:
                        await db.execute(
                            update(Call)
                            .where(Call.id.in_(stale_ids))
                            .values(
                                status="interrupted",
                                end_time=datetime.now(timezone.utc),
                            )
                        )
                        await db.commit()
                        logger.warning(
                            f"[ARI] Watchdog: {len(stale_ids)} appel(s) bloqué(s) → interrupted"
                        )
            except Exception as exc:
                logger.error(f"[ARI] Watchdog erreur: {exc}", exc_info=True)
            await asyncio.sleep(INTERVAL_S)

    async def _presynthesize_patient_messages(
        self, prenom: str, nom: str, state: Dict[str, Any]
    ) -> None:
        """
        Pré-synthétise les messages contenant {{prénom}}/{{nom}} pendant la sonnerie.

        Ces messages sont toujours des cache misses au démarrage (le warm-up génère
        les templates bruts, pas les versions interpolées). En les synthétisant ici,
        on transforme les ~500ms de latence en cache HITs lors de l'appel réel.

        Appelé en background depuis originate(), s'exécute pendant les ~5s de sonnerie.
        """
        messages = [
            (self._interpolate(PERSON_CHECK_QUESTION, state), "person_check_q"),
            (self._interpolate(PERSON_CHECK_RETRY, state), "person_check_retry"),
            (self._interpolate(PROCHE_QUESTION, state), "proche_question"),
            (self._interpolate(CONSENT_QUESTION_PROCHE, state), "consent_proche"),
        ]
        for text, hint in messages:
            try:
                await self._synthesize(text, hint)
            except Exception as exc:
                logger.debug(f"[ARI] Pre-synth {hint} error (non-fatal): {exc}")
        logger.debug(f"[ARI] Messages patient pré-synthétisés pour {prenom} {nom}")

    async def warm_up_tts_cache(self) -> None:
        """Pré-synthétise tous les textes TTS statiques au démarrage.

        Cela élimine le délai Azure (~500–2000 ms) sur le premier appel réel pour :
        - Les 20 ACKs (neutre + empathique)
        - Les messages de clôture, alerte, transfert échoué
        - Les messages hors périmètre + re-prompts (4 variants)
        - Skip, retry prefix
        - Les 7 questions par défaut + leurs sous-questions (avec préfixes ordinaux)
        """
        if not azure_tts_service.is_sdk_configured:
            logger.info("[ARI] TTS cache warm-up ignoré (SDK Azure non configuré)")
            return

        logger.info("[ARI] TTS cache warm-up démarrage…")
        t0 = time.time()

        # Collecte de tous les SSML à pré-synthétiser
        ssml_items: list[str] = []

        def _add_text(text: str) -> None:
            ssml_items.append(azure_tts_service.build_ssml(text))

        def _add_ssml(ssml: str) -> None:
            ssml_items.append(ssml)

        # ACKs neutres avec leur rate/pitch spécifiques
        for text, rate, pitch in ACK_ENTRIES_NEUTRAL:
            _add_ssml(azure_tts_service.build_ssml(text, rate=rate, pitch=pitch))

        # Messages depuis la DB — patient ET proche (prioritaires sur les fallbacks Python)
        try:
            from app.database import AsyncSessionLocal
            from app.services.telephony.questionnaire_loader import load_messages_for_service
            async with AsyncSessionLocal() as _db:
                db_msgs_patient = await load_messages_for_service(_db, service_code=None, caller_role="patient")
                db_msgs_proche = await load_messages_for_service(_db, service_code=None, caller_role="proche")
            for _msgs in (db_msgs_patient, db_msgs_proche):
                for key in ("welcome", "outro_normal", "outro_alert", "outro_transfer_failed"):
                    if _msgs.get(key):
                        _add_text(_msgs[key])
        except Exception as _e:
            logger.debug(f"[ARI] Warm-up DB messages ignoré: {_e}")

        # Messages statiques (fallback Python) — versions patient et proche
        for msg in (
            CLOSING_MESSAGE_NORMAL,
            CLOSING_MESSAGE_NORMAL_PROCHE,
            CLOSING_MESSAGE_ALERT,
            CLOSING_MESSAGE_TRANSFER_FAILED,
            CLOSING_MESSAGE_TRANSFER_FAILED_PROCHE,
            NO_ACTIVE_QUESTIONS_MESSAGE,
            OUT_OF_SCOPE_MESSAGE,
            SKIP_MESSAGE,
            PERSON_CHECK_QUESTION,
            PERSON_CHECK_RETRY,
            PROCHE_QUESTION,
            PERSON_NOT_FOUND_MESSAGE,
            CONSENT_QUESTION,
            CONSENT_QUESTION_PROCHE,
            CONSENT_REFUSED_MESSAGE,
        ):
            _add_text(msg)

        # Préfixes de retry
        for prefix in RETRY_PREFIXES:
            _add_text(prefix)

        # Messages hors périmètre + re-prompt (toutes les variantes de type)
        for qtype, choices in (
            ("yesno", None),
            ("score", None),
            ("open", None),
            ("choice", ["totalement", "moyennement", "légèrement", "pas du tout", "non"]),
        ):
            tail = short_reprompt_after_out_of_scope(qtype, choices)
            _add_text(f"{OUT_OF_SCOPE_MESSAGE}{tail}")

        # Questions par défaut (questionnaire Python) avec et sans préfixe ordinal
        _ORDINALS = [
            "Première question :", "Deuxième question :", "Troisième question :",
            "Quatrième question :", "Cinquième question :", "Sixième question :",
            "Septième question :", "Huitième question :", "Neuvième question :",
            "Dixième question :",
        ]
        for i, q in enumerate(QUESTIONNAIRE):
            q_text = q["question"]
            q_text_proche = q.get("question_proche", "")
            # Avec ordinal (première pose) — versions patient et proche
            if i < len(_ORDINALS):
                _add_text(f"{_ORDINALS[i]} {q_text}")
                if q_text_proche:
                    _add_text(f"{_ORDINALS[i]} {q_text_proche}")
            # Sans ordinal (retry) — versions patient et proche
            _add_text(q_text)
            if q_text_proche:
                _add_text(q_text_proche)
            # Sous-questions — versions patient et proche
            for fu in q.get("follow_ups", []):
                _add_text(fu["question"])
                if fu.get("question_proche"):
                    _add_text(fu["question_proche"])

        # Déduplique (certains textes pourraient produire le même SSML)
        seen: set[str] = set()
        unique_ssml: list[str] = []
        for ssml in ssml_items:
            key = hashlib.sha256(ssml.encode()).hexdigest()[:16]
            if key not in seen:
                seen.add(key)
                unique_ssml.append(ssml)

        # Synthèse en batches de 5 pour ne pas saturer l'API Azure
        hits = 0
        misses = 0
        errors = 0

        async def _warm_one(ssml: str) -> None:
            nonlocal hits, misses, errors
            key = hashlib.sha256(ssml.encode()).hexdigest()[:16]
            cache_path = TTS_CACHE_DIR / f"{key}.wav"
            if cache_path.exists():
                hits += 1
                return
            audio = await azure_tts_service.synthesize_to_bytes(ssml, use_ssml=True)
            if audio:
                cache_path.write_bytes(audio)
                misses += 1
            else:
                errors += 1

        batch_size = 5
        for i in range(0, len(unique_ssml), batch_size):
            await asyncio.gather(*[_warm_one(s) for s in unique_ssml[i:i + batch_size]])

        elapsed = time.time() - t0
        logger.info(
            f"[ARI] TTS cache warm-up terminé en {elapsed:.1f}s — "
            f"{hits} hits · {misses} nouveaux · {errors} erreurs "
            f"({len(unique_ssml)} entrées)"
        )

        # ── Fichiers statiques nommés (static_{key}.wav + ack_{i}.wav) ───────
        # Ces fichiers sont détectés par _static() et servent les messages fixes
        # sans passer par Azure. Générés une seule fois si absents.
        await self._ensure_static_files()

    async def _ensure_static_files(self) -> None:
        """Génère les fichiers static_{key}.wav et ack_{i}.wav si absents.

        Appelé depuis warm_up_tts_cache() au démarrage — idempotent (skip si présent).
        """
        from app.services.telephony.questionnaire import (
            OUT_OF_SCOPE_MESSAGE,
            RETRY_PREFIXES,
            SKIP_MESSAGE,
            short_reprompt_after_out_of_scope,
        )

        static_map: list[tuple[str, str]] = [
            ("retry_prefix",       RETRY_PREFIXES[0]),
            ("skip",               SKIP_MESSAGE),
            ("out_of_scope",       OUT_OF_SCOPE_MESSAGE),
            ("reprompt_yesno",     short_reprompt_after_out_of_scope("yesno")),
            ("reprompt_score",     short_reprompt_after_out_of_scope("score")),
            ("reprompt_open",      short_reprompt_after_out_of_scope("open")),
        ]

        generated = 0
        for key, text in static_map:
            path = TTS_CACHE_DIR / f"static_{key}.wav"
            if path.exists():
                continue
            ssml = azure_tts_service.build_ssml(text)
            audio = await azure_tts_service.synthesize_to_bytes(ssml, use_ssml=True)
            if audio:
                path.write_bytes(audio)
                generated += 1
                logger.debug(f"[ARI] static_{key}.wav généré ({len(audio):,} bytes)")
            else:
                logger.warning(f"[ARI] Échec génération static_{key}.wav")

        if generated:
            logger.info(f"[ARI] {generated} fichiers statiques TTS générés")

    # ── Statut ────────────────────────────────────────────────────────────────

    async def get_call_status(self, channel_id: str) -> Optional[Dict[str, Any]]:
        return await self._get_state(channel_id)

    async def health_check(self) -> bool:
        """Vérifie que l'API ARI Asterisk répond."""
        try:
            result = await self._get("/asterisk/info")
            return result is not None
        except Exception:
            return False


# Instance globale
asterisk_ari_service = AsteriskARIService()
