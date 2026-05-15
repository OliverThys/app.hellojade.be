"""
Service de configuration — HelloJADE Epicura

Lit les paramètres depuis la table `settings` (DB) avec fallback sur les
variables d'environnement. Permet de modifier la configuration en live
(sans restart) pour les paramètres d'application.

Les paramètres d'infrastructure (DB, Redis) sont exposés en lecture seule.
Les valeurs sensibles sont masquées en retour d'API.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.setting import Setting

logger = get_logger(__name__)

# Marqueur utilisé pour signifier "ne pas modifier ce secret"
SECRET_PLACEHOLDER = "••••••••"

# ---------------------------------------------------------------------------
# Clés sensibles → masquées en GET
# ---------------------------------------------------------------------------
_SECRET_KEYWORDS = (
    "KEY", "PASSWORD", "SECRET", "TOKEN", "CERT", "CREDENTIALS",
    "PRIVATE", "PWD", "PASSWD",
)

# ---------------------------------------------------------------------------
# Clés en lecture seule (infrastructure Docker)
# ---------------------------------------------------------------------------
_READONLY_KEYS = {
    "POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB",
    "POSTGRES_USER", "POSTGRES_PASSWORD",
    "REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD", "REDIS_DB",
    "DATABASE_URL", "REDIS_URL",
}

# ---------------------------------------------------------------------------
# Définition des sections et de leurs champs
# ---------------------------------------------------------------------------

_FIELD_TYPE = Dict[str, Any]

def _field(
    key: str,
    label: str,
    field_type: str = "text",
    placeholder: str = "",
    hint: str = "",
    options: Optional[List[Dict]] = None,
) -> _FIELD_TYPE:
    return {
        "key": key,
        "label": label,
        "type": field_type,
        "placeholder": placeholder,
        "hint": hint,
        "options": options or [],
        "readonly": key in _READONLY_KEYS,
        "secret": any(kw in key.upper() for kw in _SECRET_KEYWORDS),
    }


CONFIG_SECTIONS: List[Dict[str, Any]] = [
    {
        "id": "application",
        "label": "Application",
        "icon": "Settings",
        "description": "Paramètres généraux de l'application",
        "readonly": False,
        "fields": [
            _field("APP_NAME", "Nom de l'application", placeholder="HelloJADE"),
            _field("APP_ENV", "Environnement", "select", options=[
                {"value": "development", "label": "Développement"},
                {"value": "staging", "label": "Pré-production"},
                {"value": "production", "label": "Production"},
            ]),
            _field("APP_DEBUG", "Mode debug", "boolean"),
            _field("FRONTEND_URL", "URL Frontend", placeholder="https://hellojadeapp.local"),
            _field("APP_URL", "URL de l'API", placeholder="http://localhost:8001"),
        ],
    },
    {
        "id": "security",
        "label": "Sécurité",
        "icon": "Shield",
        "description": "Clés JWT, tokens et sécurité",
        "readonly": False,
        "fields": [
            _field("SECRET_KEY", "Clé secrète JWT", "password", hint="Minimum 32 caractères"),
            _field("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "Expiration access token (min)", "number", placeholder="15"),
            _field("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "Expiration refresh token (jours)", "number", placeholder="7"),
            _field("BCRYPT_ROUNDS", "Rounds bcrypt", "number", placeholder="12"),
            _field("RATE_LIMIT_PER_MINUTE", "Limite requêtes / minute", "number", placeholder="60"),
            _field("RATE_LIMIT_LOGIN_ATTEMPTS", "Tentatives login max", "number", placeholder="20"),
        ],
    },
    {
        "id": "database",
        "label": "Base de données",
        "icon": "Database",
        "description": "Connexion PostgreSQL — modifier dans le .env et redémarrer",
        "readonly": True,
        "fields": [
            _field("POSTGRES_HOST", "Hôte PostgreSQL"),
            _field("POSTGRES_PORT", "Port", "number"),
            _field("POSTGRES_DB", "Nom de la base"),
            _field("POSTGRES_USER", "Utilisateur"),
            _field("POSTGRES_PASSWORD", "Mot de passe", "password"),
        ],
    },
    {
        "id": "redis",
        "label": "Redis",
        "icon": "Cpu",
        "description": "Connexion Redis (Celery/cache) — modifier dans le .env et redémarrer",
        "readonly": True,
        "fields": [
            _field("REDIS_HOST", "Hôte Redis"),
            _field("REDIS_PORT", "Port", "number"),
            _field("REDIS_PASSWORD", "Mot de passe", "password"),
            _field("REDIS_DB", "Base Redis", "number"),
        ],
    },
    {
        "id": "azure_speech",
        "label": "Azure Speech",
        "icon": "Mic",
        "description": "Reconnaissance vocale et synthèse (STT/TTS)",
        "readonly": False,
        "fields": [
            _field("AZURE_SPEECH_KEY", "Clé API Azure Speech", "password"),
            _field("AZURE_SPEECH_REGION", "Région Azure", placeholder="westeurope"),
            _field("AZURE_TTS_VOICE", "Voix TTS", placeholder="fr-BE-CharlineNeural",
                   hint="Voix neurale Azure (fr-BE-CharlineNeural, fr-FR-DeniseNeural...)"),
            _field("AZURE_STT_LANGUAGE", "Langue STT", placeholder="fr-BE"),
        ],
    },
    {
        "id": "ai",
        "label": "IA (Mistral / Azure OpenAI)",
        "icon": "Brain",
        "description": "Modèles d'analyse médicale",
        "readonly": False,
        "fields": [
            _field("MISTRAL_API_KEY", "Clé API Mistral", "password"),
            _field("MISTRAL_MODEL", "Modèle Mistral", placeholder="mistral-small-latest"),
            _field("MISTRAL_BASE_URL", "URL API Mistral", placeholder="https://api.mistral.ai/v1"),
            _field("AZURE_OPENAI_ENDPOINT", "Endpoint Azure OpenAI", placeholder="https://<resource>.openai.azure.com"),
            _field("AZURE_OPENAI_API_KEY", "Clé Azure OpenAI", "password"),
            _field("AZURE_OPENAI_DEPLOYMENT", "Déploiement Azure OpenAI", placeholder="gpt-4o-mini"),
        ],
    },
    {
        "id": "telephony",
        "label": "Téléphonie (Asterisk)",
        "icon": "Phone",
        "description": "Connexion Asterisk ARI et paramètres d'appel",
        "readonly": False,
        "fields": [
            _field("ASTERISK_ARI_URL", "URL ARI Asterisk", placeholder="http://localhost:8088"),
            _field("ASTERISK_ARI_USER", "Utilisateur ARI", placeholder="hellojadeapp"),
            _field("ASTERISK_ARI_PASSWORD", "Mot de passe ARI", "password"),
            _field("ASTERISK_ARI_APP", "Nom application Stasis", placeholder="hellojadeapp"),
            _field("ASTERISK_CALLER_NUMBER", "Numéro appelant (E.164)", placeholder="+3227000000"),
            _field("ASTERISK_TRUNK", "Trunk SIP", placeholder="ovh-sip"),
            _field("TRANSFER_NUMBER", "Numéro transfert alerte (E.164)", placeholder="+3265000000"),
            _field("TRANSFER_MODE", "Mode transfert", "select", options=[
                {"value": "real", "label": "Réel (appel effectif)"},
                {"value": "simulate", "label": "Simulé (log uniquement)"},
                {"value": "disabled", "label": "Désactivé"},
            ]),
        ],
    },
    {
        "id": "hl7",
        "label": "HL7 / Mirth",
        "icon": "Network",
        "description": "Intégration Mirth Connect (import patients ADT, export rapports ORU)",
        "readonly": False,
        "fields": [
            _field("HL7_API_KEY", "Clé API HL7 (partagée avec Mirth)", "password"),
            _field("HL7_AUTO_SCHEDULE_CALLS", "Planifier appel auto après ADT A03", "boolean"),
            _field("MIRTH_TRANSPORT", "Transport ORU", "select", options=[
                {"value": "http", "label": "HTTP POST"},
                {"value": "sftp", "label": "SFTP"},
                {"value": "local", "label": "Local (fichier uniquement)"},
            ]),
            _field("MIRTH_HTTP_URL", "URL HTTP Listener Mirth", placeholder="http://mirth.epicura.local:8080/hl7"),
            _field("MIRTH_SFTP_HOST", "Hôte SFTP Mirth", placeholder="sftp.epicura.local"),
            _field("MIRTH_SFTP_PORT", "Port SFTP", "number", placeholder="22"),
            _field("MIRTH_SFTP_USER", "Utilisateur SFTP"),
            _field("MIRTH_SFTP_PASSWORD", "Mot de passe SFTP", "password"),
            _field("MIRTH_SFTP_PATH", "Chemin dépôt SFTP", placeholder="/hl7/incoming"),
        ],
    },
    {
        "id": "backup",
        "label": "Backup SMB",
        "icon": "HardDrive",
        "description": "Sauvegarde automatique vers le NAS Epicura",
        "readonly": False,
        "fields": [
            _field("BACKUP_ENABLED", "Backup activé", "boolean"),
            _field("BACKUP_RETENTION_DAYS", "Rétention (jours)", "number", placeholder="30"),
            _field("BACKUP_SCHEDULE", "Planification cron", placeholder="0 2 * * *",
                   hint="Format cron : minute heure jour mois jour-semaine"),
            _field("SMB_HOST", "Hôte NAS SMB", placeholder="nas.epicura.local"),
            _field("SMB_SHARE", "Nom du share", placeholder="backup_hellojade"),
            _field("SMB_USER", "Utilisateur SMB", placeholder="svc_hellojade"),
            _field("SMB_PASSWORD", "Mot de passe SMB", "password"),
            _field("SMB_DOMAIN", "Domaine AD", placeholder="EPICURA"),
        ],
    },
    {
        "id": "notifications",
        "label": "RGPD & Notifications",
        "icon": "Bell",
        "description": "SMTP, RGPD et feature flags",
        "readonly": False,
        "fields": [
            _field("SMTP_HOST", "Serveur SMTP", placeholder="smtp.epicura.local"),
            _field("SMTP_PORT", "Port SMTP", "number", placeholder="587"),
            _field("SMTP_USER", "Utilisateur SMTP"),
            _field("SMTP_PASSWORD", "Mot de passe SMTP", "password"),
            _field("SMTP_FROM", "Adresse expéditeur", placeholder="noreply@hellojadeapp.com"),
            _field("SMTP_TLS", "TLS activé", "boolean"),
            _field(
                "GDPR_DATA_RETENTION_YEARS",
                "Rétention données (années)",
                "number",
                placeholder="10",
                hint="Valeur lue pour les exports RGPD (cf. export patient). La purge automatique "
                "peut reposer sur d'autres jobs selon l'infra.",
            ),
            _field("GDPR_DPO_EMAIL", "Email DPO", placeholder="dpo@hellojadeapp.com"),
            _field("GDPR_DPO_PHONE", "Téléphone DPO", placeholder="+3227123457"),
            _field("FEATURE_AUTO_CALLS", "Appels automatiques", "boolean"),
            _field("FEATURE_AI_ANALYSIS", "Analyse IA", "boolean"),
            _field("FEATURE_PDF_REPORTS", "Rapports PDF", "boolean"),
            _field("FEATURE_EMAIL_NOTIFICATIONS", "Notifications email", "boolean"),
            _field("FEATURE_VOICE_SYNTHESIS", "Synthèse vocale", "boolean"),
        ],
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_secret(key: str) -> bool:
    return any(kw in key.upper() for kw in _SECRET_KEYWORDS)


def _is_readonly(key: str) -> bool:
    return key in _READONLY_KEYS


def _mask(key: str, value: str) -> str:
    """Retourne le placeholder si la valeur est sensible et non vide."""
    if _is_secret(key) and value:
        return SECRET_PLACEHOLDER
    return value


def _env_value(key: str) -> str:
    """Lit une valeur depuis les variables d'environnement."""
    return os.environ.get(key, "")


# ---------------------------------------------------------------------------
# Service principal
# ---------------------------------------------------------------------------

class ConfigService:
    """Accès aux paramètres de configuration depuis la DB ou les env vars."""

    async def get_all_sections(self, db: AsyncSession) -> List[Dict[str, Any]]:
        """
        Retourne toutes les sections avec leur valeur courante.
        Les secrets sont masqués.
        """
        db_settings = await self._load_db_settings(db)
        result = []
        for section_def in CONFIG_SECTIONS:
            fields_with_values = []
            for field in section_def["fields"]:
                key = field["key"]
                db_val = db_settings.get(key)
                env_val = _env_value(key)
                raw = db_val if db_val is not None else env_val
                fields_with_values.append({
                    **field,
                    "value": _mask(key, raw),
                    "source": "db" if db_val is not None else "env",
                })
            result.append({
                **section_def,
                "fields": fields_with_values,
            })
        return result

    async def get_section(self, section_id: str, db: AsyncSession) -> Optional[Dict[str, Any]]:
        """Retourne une section spécifique avec ses valeurs."""
        section_def = next((s for s in CONFIG_SECTIONS if s["id"] == section_id), None)
        if not section_def:
            return None

        db_settings = await self._load_db_settings(db)
        fields_with_values = []
        for field in section_def["fields"]:
            key = field["key"]
            db_val = db_settings.get(key)
            env_val = _env_value(key)
            raw = db_val if db_val is not None else env_val
            fields_with_values.append({
                **field,
                "value": _mask(key, raw),
                "source": "db" if db_val is not None else "env",
            })
        return {**section_def, "fields": fields_with_values}

    async def update_section(
        self,
        section_id: str,
        updates: Dict[str, str],
        db: AsyncSession,
        updated_by: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Met à jour les paramètres d'une section dans la DB.
        Si la valeur reçue est SECRET_PLACEHOLDER, le champ est ignoré
        (conservation de la valeur existante).
        Les champs readonly sont ignorés silencieusement.
        """
        section_def = next((s for s in CONFIG_SECTIONS if s["id"] == section_id), None)
        if not section_def:
            raise ValueError(f"Section inconnue: {section_id}")

        if section_def.get("readonly"):
            raise ValueError(f"La section '{section_id}' est en lecture seule")

        # Charger les valeurs DB actuelles pour comparer
        db_settings = await self._load_db_settings(db)

        saved_keys: List[str] = []
        for field in section_def["fields"]:
            key = field["key"]
            if key not in updates:
                continue
            if field.get("readonly") or _is_readonly(key):
                continue

            new_value = updates[key]

            # Ne pas écraser un secret avec le placeholder
            if new_value == SECRET_PLACEHOLDER:
                continue

            # Sauvegarder la valeur précédente pour audit
            previous = db_settings.get(key)

            await self._upsert_setting(
                db=db,
                key=key,
                value=new_value,
                category=section_id,
                is_sensitive=_is_secret(key),
                previous_value=previous,
                updated_by=updated_by,
            )
            saved_keys.append(key)

        await db.commit()
        logger.info(f"[Config] Section '{section_id}' mise à jour: {saved_keys}")
        return {"updated_keys": saved_keys, "section": section_id}

    async def get_raw_value(self, key: str, db: AsyncSession) -> Optional[str]:
        """
        Retourne la valeur brute (non masquée) d'un paramètre.
        À utiliser uniquement en interne (test de connectivité, etc.).
        """
        db_settings = await self._load_db_settings(db)
        return db_settings.get(key) or _env_value(key) or None

    # ------------------------------------------------------------------
    # Méthodes privées
    # ------------------------------------------------------------------

    async def _load_db_settings(self, db: AsyncSession) -> Dict[str, str]:
        """Charge tous les paramètres depuis la DB sous forme key→value (str)."""
        result = await db.execute(select(Setting))
        settings = result.scalars().all()
        out: Dict[str, str] = {}
        for s in settings:
            val = s.value
            if isinstance(val, dict) and "value" in val:
                out[s.key] = str(val["value"])
            else:
                out[s.key] = str(val)
        return out

    async def _upsert_setting(
        self,
        db: AsyncSession,
        key: str,
        value: str,
        category: str,
        is_sensitive: bool,
        previous_value: Optional[str],
        updated_by: Optional[UUID],
    ) -> None:
        """Upsert d'un paramètre dans la table settings."""
        json_value: Dict[str, Any] = {"value": value}
        json_previous: Optional[Dict[str, Any]] = (
            {"value": previous_value} if previous_value is not None else None
        )

        stmt = (
            pg_insert(Setting)
            .values(
                key=key,
                value=json_value,
                category=category,
                is_sensitive=is_sensitive,
                previous_value=json_previous,
                updated_by=updated_by,
            )
            .on_conflict_do_update(
                index_elements=["key"],
                set_={
                    "value": json_value,
                    "previous_value": json_previous,
                    "updated_by": updated_by,
                    "updated_at": __import__("sqlalchemy").func.now(),
                },
            )
        )
        await db.execute(stmt)


config_service = ConfigService()
