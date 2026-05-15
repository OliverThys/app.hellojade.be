"""
Lecteur en cache des paramètres d'appel (admin.call_settings) depuis la DB.

Cache mémoire de 60 secondes pour éviter des requêtes DB dans chaque événement ARI.
Expose aussi les utilitaires de planification (fenêtre horaire, prochaine plage valide).
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app.core.logging import get_logger

logger = get_logger(__name__)

_KEY_CALL_SETTINGS = "admin.call_settings"

DEFAULTS: Dict[str, Any] = {
    "delay_after_discharge_hours": 24,
    "call_window_start": "09:00",
    "call_window_end": "19:00",
    "allowed_days": ["mon", "tue", "wed", "thu", "fri"],
    "max_attempts": 3,
    "retry_delay_hours": 4,
    "amd_behavior": "retry",
    "max_call_duration_minutes": 10,
    "silence_timeout_seconds": 1,
}

_CACHE_TTL = 60  # secondes

_DAY_MAP = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}

try:
    from zoneinfo import ZoneInfo
    _BRUSSELS = ZoneInfo("Europe/Brussels")
except Exception:
    _BRUSSELS = None  # type: ignore[assignment]


class CallSettingsService:
    """Singleton qui lit et met en cache les paramètres d'appel depuis la table Setting."""

    def __init__(self) -> None:
        self._cached: Optional[Dict[str, Any]] = None
        self._cached_at: float = 0.0
        self._lock: Optional[asyncio.Lock] = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def get(self) -> Dict[str, Any]:
        """Retourne les paramètres depuis le cache ou la DB."""
        now = time.monotonic()
        if self._cached is not None and (now - self._cached_at) < _CACHE_TTL:
            return self._cached

        async with self._get_lock():
            now = time.monotonic()
            if self._cached is not None and (now - self._cached_at) < _CACHE_TTL:
                return self._cached
            loaded = await self._load()
            self._cached = loaded
            self._cached_at = time.monotonic()
            return self._cached

    def get_sync(self) -> Dict[str, Any]:
        """Version synchrone pour les workers Celery (utilise le cache si disponible)."""
        if self._cached is not None and (time.monotonic() - self._cached_at) < _CACHE_TTL:
            return self._cached
        return asyncio.run(self._load())

    def invalidate(self) -> None:
        """Force un rechargement au prochain accès (appeler après sauvegarde des paramètres)."""
        self._cached = None
        self._cached_at = 0.0

    async def _load(self) -> Dict[str, Any]:
        try:
            from app.database import AsyncSessionLocal
            from app.models.setting import Setting
            from sqlalchemy import select

            async with AsyncSessionLocal() as db:
                row = await db.scalar(
                    select(Setting).where(Setting.key == _KEY_CALL_SETTINGS)
                )
                if row and isinstance(row.value, dict):
                    v = row.value
                    # _set_setting enveloppe les scalaires dans {"value": x}
                    # mais pour un dict (model_dump), il le stocke directement
                    if "value" in v and len(v) == 1 and isinstance(v["value"], dict):
                        return {**DEFAULTS, **v["value"]}
                    return {**DEFAULTS, **v}
        except Exception as exc:
            logger.warning(f"[CallSettings] Impossible de charger depuis DB: {exc}")
        return dict(DEFAULTS)


# ── Utilitaires de planification ──────────────────────────────────────────────

def is_within_call_window(cs: Dict[str, Any], dt: Optional[datetime] = None) -> bool:
    """
    Vérifie si dt (UTC, défaut = maintenant) tombe dans la fenêtre d'appel.
    Les horaires configurés sont interprétés en heure de Bruxelles.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    dt_local = _to_brussels(dt)

    day = _DAY_MAP[dt_local.weekday()]
    if day not in cs.get("allowed_days", DEFAULTS["allowed_days"]):
        return False

    current_hm = dt_local.strftime("%H:%M")
    return (
        cs.get("call_window_start", "09:00")
        <= current_hm
        < cs.get("call_window_end", "19:00")
    )


def next_valid_window(dt: datetime, cs: Dict[str, Any]) -> datetime:
    """
    Retourne la prochaine datetime (UTC) à partir de dt qui tombe dans un
    créneau autorisé (jour de la semaine + fenêtre horaire).

    - Si dt est déjà dans la fenêtre → retourne dt inchangé.
    - Sinon avance au début de la prochaine plage valide (max 14 jours ahead).
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    allowed_days: list = cs.get("allowed_days", DEFAULTS["allowed_days"])
    window_start: str = cs.get("call_window_start", "09:00")
    window_end: str = cs.get("call_window_end", "19:00")

    ws_h, ws_m = map(int, window_start.split(":"))
    we_h, we_m = map(int, window_end.split(":"))

    dt_local = _to_brussels(dt)

    for _ in range(14):
        day = _DAY_MAP[dt_local.weekday()]
        if day in allowed_days:
            win_start = dt_local.replace(hour=ws_h, minute=ws_m, second=0, microsecond=0)
            win_end = dt_local.replace(hour=we_h, minute=we_m, second=0, microsecond=0)
            if win_start <= dt_local < win_end:
                # Déjà dans la fenêtre
                return dt_local.astimezone(timezone.utc)
            if dt_local < win_start:
                # Avant l'ouverture ce jour → avancer au début
                return win_start.astimezone(timezone.utc)

        # Passer au lendemain à l'heure d'ouverture
        dt_local = (dt_local + timedelta(days=1)).replace(
            hour=ws_h, minute=ws_m, second=0, microsecond=0
        )

    return dt  # fallback : retourner dt inchangé


def _to_brussels(dt: datetime) -> datetime:
    """Convertit une datetime UTC (ou naïve) en heure de Bruxelles."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if _BRUSSELS is not None:
        return dt.astimezone(_BRUSSELS)
    # Fallback sans zoneinfo : UTC+1 (approximation)
    return dt.astimezone(timezone(timedelta(hours=1)))


# Singleton partagé dans tout le backend
call_settings_service = CallSettingsService()
