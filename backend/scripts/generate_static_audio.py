"""
Génère tous les fichiers audio statiques pour JADE.

Ces fichiers sont stockés dans TEMP_PATH/tts/cache/ sous deux formes :
  - static_{key}.wav  : messages fixes nommés explicitement (identity, retry, skip…)
  - ack_{i}.wav       : vocalisations d'écoute (hum hum, avec prosody SSML spécifique)

Par défaut, les fichiers déjà présents sont conservés (skip).
Utiliser --force pour tout régénérer.

Usage dans le container :
    python3 /app/scripts/generate_static_audio.py
    python3 /app/scripts/generate_static_audio.py --force
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Rendre le package /app importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.services.ai.azure_tts_service import azure_tts_service
from app.services.telephony.questionnaire import (
    ACK_HUM_ENTRIES,
    IDENTITY_CONFIRMED_MESSAGE,
    IDENTITY_FAILED_MESSAGE,
    IDENTITY_PENDING_MESSAGE,
    IDENTITY_QUESTION,
    IDENTITY_RETRY_MESSAGE,
    OUT_OF_SCOPE_MESSAGE,
    RETRY_PREFIXES,
    SKIP_MESSAGE,
    short_reprompt_after_out_of_scope,
)

TTS_CACHE_DIR = Path(settings.TEMP_PATH) / "tts" / "cache"

# ── Fichiers static_{key}.wav ─────────────────────────────────────────────────
#
# Chaque entrée : (clé, texte, rate, pitch)
# rate/pitch = None → valeurs par défaut Azure ("medium")

STATIC_ENTRIES: list[tuple[str, str, str, str]] = [
    # Identité
    ("identity_question",   IDENTITY_QUESTION,           "medium", "medium"),
    ("identity_pending",    IDENTITY_PENDING_MESSAGE,    "medium", "medium"),
    ("identity_confirmed",  IDENTITY_CONFIRMED_MESSAGE,  "medium", "medium"),
    ("identity_retry",      IDENTITY_RETRY_MESSAGE,      "medium", "medium"),
    ("identity_failed",     IDENTITY_FAILED_MESSAGE,     "medium", "medium"),
    # Navigation
    ("retry_prefix",        RETRY_PREFIXES[0],           "medium", "medium"),
    ("skip",                SKIP_MESSAGE,                "medium", "medium"),
    # Hors périmètre
    ("out_of_scope",        OUT_OF_SCOPE_MESSAGE,        "medium", "medium"),
    # Re-prompts courts (joués après out_of_scope)
    ("reprompt_yesno",  short_reprompt_after_out_of_scope("yesno"),  "medium", "medium"),
    ("reprompt_score",  short_reprompt_after_out_of_scope("score"),  "medium", "medium"),
    ("reprompt_open",   short_reprompt_after_out_of_scope("open"),   "medium", "medium"),
]

# ── Fichiers ack_{i}.wav ──────────────────────────────────────────────────────
#
# Vocalisations d'écoute neutres (hum hum) avec prosody SSML spécifique.
# L'index correspond à ack_0, ack_1, ack_2…

ACK_ENTRIES: list[tuple[str, str, str]] = list(ACK_HUM_ENTRIES)


async def generate(force: bool = False) -> None:
    TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if not azure_tts_service.is_sdk_configured:
        print("[ERREUR] SDK Azure non configuré (AZURE_SPEECH_KEY manquant ?)")
        sys.exit(1)

    ok = skipped = errors = 0

    async def _write(filename: str, ssml: str) -> None:
        nonlocal ok, skipped, errors
        path = TTS_CACHE_DIR / filename
        if path.exists() and not force:
            print(f"  skip  {filename}")
            skipped += 1
            return
        audio = await azure_tts_service.synthesize_to_bytes(ssml, use_ssml=True)
        if audio:
            path.write_bytes(audio)
            status = "regen" if path.exists() and force else "  ok  "
            print(f"{status}  {filename}  ({len(audio):,} bytes)")
            ok += 1
        else:
            print(f"  ERR   {filename}")
            errors += 1

    # static_{key}.wav
    print("\n── Fichiers statiques ──────────────────────────────────────────────")
    for key, text, rate, pitch in STATIC_ENTRIES:
        ssml = azure_tts_service.build_ssml(text, rate=rate, pitch=pitch)
        await _write(f"static_{key}.wav", ssml)

    # ack_{i}.wav
    print("\n── ACK (hum hum) ───────────────────────────────────────────────────")
    for i, (text, rate, pitch) in enumerate(ACK_ENTRIES):
        ssml = azure_tts_service.build_ssml(text, rate=rate, pitch=pitch)
        await _write(f"ack_{i}.wav", ssml)

    print(f"\nTerminé — {ok} générés, {skipped} existants conservés, {errors} erreurs")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Génère les fichiers audio statiques JADE")
    parser.add_argument("--force", action="store_true", help="Régénérer même si le fichier existe")
    args = parser.parse_args()
    asyncio.run(generate(force=args.force))
