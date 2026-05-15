"""
Configuration de l'application avec Pydantic Settings.
"""
from functools import lru_cache
from typing import Any, List, Optional
from pathlib import Path

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration principale de l'application"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    
    # Application
    APP_NAME: str = "HelloJADE"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = Field(default="development", env="APP_ENV")
    DEBUG: bool = Field(default=False, env="APP_DEBUG", validation_alias="APP_DEBUG")
    API_V1_PREFIX: str = "/api/v1"
    
    # Security
    SECRET_KEY: str = Field(..., min_length=32)
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    SESSION_EXPIRE_MINUTES: int = 60
    ALGORITHM: str = "HS256"
    BCRYPT_ROUNDS: int = 12
    
    # URL du frontend (pour redirection après SAML2 login)
    FRONTEND_URL: str = "https://hellojadeapp.local"

    # SAML2 / Intra ID (Epicura)
    SAML2_ENABLED: bool = False
    # URL publique de l'IdP ou metadata XML (optionnel, selon la configuration fournie par Epicura)
    SAML2_IDP_METADATA_URL: Optional[str] = None
    SAML2_IDP_ENTITY_ID: Optional[str] = None
    SAML2_IDP_SSO_URL: Optional[str] = None
    SAML2_IDP_SLO_URL: Optional[str] = None
    SAML2_IDP_X509_CERT: Optional[str] = None
    
    # Paramètres du Service Provider (HelloJADE)
    SAML2_SP_ENTITY_ID: Optional[str] = None
    SAML2_SP_ASSERTION_CONSUMER_SERVICE_URL: Optional[str] = None
    SAML2_SP_SINGLE_LOGOUT_SERVICE_URL: Optional[str] = None
    SAML2_NAMEID_FORMAT: str = (
        "urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified"
    )
    
    # Mapping des groupes / attributs
    SAML2_GROUP_ATTRIBUTE: str = "memberOf"
    SAML2_ADMIN_GROUPS: List[str] = Field(default_factory=list)
    
    # Database PostgreSQL
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "hellojadeapp"
    POSTGRES_USER: str = "hellojadeapp"
    POSTGRES_PASSWORD: str
    DATABASE_URL: Optional[PostgresDsn] = None
    
    @field_validator("DATABASE_URL", mode="before")
    def assemble_db_connection(cls, v: Optional[str], values: dict[str, Any]) -> Any:
        if isinstance(v, str):
            return v
        return PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=values.data.get("POSTGRES_USER"),
            password=values.data.get("POSTGRES_PASSWORD"),
            host=values.data.get("POSTGRES_HOST"),
            port=values.data.get("POSTGRES_PORT"),
            path=f"{values.data.get('POSTGRES_DB') or ''}",
        )
    
    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0
    REDIS_URL: Optional[RedisDsn] = None
    
    @field_validator("REDIS_URL", mode="before")
    def assemble_redis_connection(cls, v: Optional[str], values: dict[str, Any]) -> Any:
        if isinstance(v, str):
            return v
        password = values.data.get("REDIS_PASSWORD")
        if password:
            return f"redis://:{password}@{values.data.get('REDIS_HOST')}:{values.data.get('REDIS_PORT')}/{values.data.get('REDIS_DB')}"
        return f"redis://{values.data.get('REDIS_HOST')}:{values.data.get('REDIS_PORT')}/{values.data.get('REDIS_DB')}"
    
    # ═══════════════════════════════════════════════════════════════
    # EMAIL
    # ═══════════════════════════════════════════════════════════════
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM: str = "noreply@hellojadeapp.com"
    SMTP_TLS: bool = True
    
    # ═══════════════════════════════════════════════════════════════
    # SECURITY & CORS
    # ═══════════════════════════════════════════════════════════════
    CORS_ORIGINS: List[str] = Field(
        default=[
            "http://localhost:3000",
            "http://localhost:5173",
            "http://localhost:5174",
            "tauri://localhost",
            "http://tauri.localhost",
            "http://127.0.0.1:8001",
            "http://localhost:8001",
            # Autoriser tous les clients Tauri sur le réseau local
            "*",  # Permet l'accès depuis n'importe quelle origine (à restreindre en production)
        ]
    )

    TRUSTED_HOSTS: List[str] = Field(
        default=[
            "localhost",
            "127.0.0.1",
            "hellojadeapp.com",
            "*.hellojadeapp.be",
            "webhook.hellojadeapp.be",
            "backend",
            # Autoriser les IPs locales (réseau 192.168.x.x et 172.x.x.x)
            "*.192.168.*",
            "*.172.*",
            "*.10.*",
        ]
    )
    
    # ═══════════════════════════════════════════════════════════════
    # MONITORING
    # ═══════════════════════════════════════════════════════════════
    PROMETHEUS_ENABLED: bool = True
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    LOG_FILE_PATH: Path = Path("/app/logs")
    
    # Rate limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_LOGIN_ATTEMPTS: int = 20  # Augmenté pour éviter les blocages en développement
    RATE_LIMIT_LOGIN_WINDOW_MINUTES: int = 5  # Réduit à 5 minutes au lieu de 15
    
    # ═══════════════════════════════════════════════════════════════
    # CELERY
    # ═══════════════════════════════════════════════════════════════
    CELERY_BROKER_URL: Optional[str] = None
    CELERY_RESULT_BACKEND: Optional[str] = None
    @field_validator("CELERY_BROKER_URL", mode="before")
    def set_celery_broker(cls, v: Optional[str], values: dict[str, Any]) -> str:
        if v:
            return v
        redis_url = values.data.get("REDIS_URL") or "redis://localhost:6379/0"
        return str(redis_url)
    
    @field_validator("CELERY_RESULT_BACKEND", mode="before")
    def set_celery_backend(cls, v: Optional[str], values: dict[str, Any]) -> str:
        if v:
            return v
        redis_url = values.data.get("REDIS_URL") or "redis://localhost:6379/1"
        redis_url_str = str(redis_url)
        if redis_url_str.endswith("/0"):
            return redis_url_str[:-1] + "1"
        return redis_url_str
    
    # ═══════════════════════════════════════════════════════════════
    # RGPD
    # ═══════════════════════════════════════════════════════════════
    GDPR_DATA_RETENTION_YEARS: int = 10
    GDPR_DPO_EMAIL: str = "dpo@hellojadeapp.com"
    GDPR_DPO_PHONE: str = "+3227123457"
    
    # ═══════════════════════════════════════════════════════════════
    # PATHS
    # ═══════════════════════════════════════════════════════════════
    RECORDINGS_PATH: Path = Path("/app/recordings")
    REPORTS_PATH: Path = Path("/app/reports")
    DOCUMENTS_PATH: Path = Path("/app/documents")
    TEMP_PATH: Path = Path("/app/temp")
    BACKUP_PATH: Path = Path("/backups")
    
    # ═══════════════════════════════════════════════════════════════
    # HL7 / MIRTH INTEGRATION (Epicura)
    # ═══════════════════════════════════════════════════════════════
    HL7_API_KEY: str = Field(default="", description="API key partagée avec Mirth pour l'auth HL7")
    HL7_AUTO_SCHEDULE_CALLS: bool = Field(default=True, description="Planifier auto les appels après import ADT A03")
    HL7_AUTO_SEND_ORU: bool = Field(default=False, description="Envoyer automatiquement les ORU^R01 à Mirth après génération du PDF")

    # Transport ORU vers Mirth
    MIRTH_TRANSPORT: str = Field(default="http", description="Mode transport ORU: http ou sftp")
    MIRTH_HTTP_URL: str = Field(default="", description="URL Mirth HTTP Listener (ex: http://mirth.epicura.local:8080/hl7)")
    MIRTH_SFTP_HOST: str = Field(default="", description="Hôte SFTP Mirth")
    MIRTH_SFTP_PORT: int = Field(default=22, description="Port SFTP Mirth")
    MIRTH_SFTP_USER: str = Field(default="", description="Utilisateur SFTP Mirth")
    MIRTH_SFTP_PASSWORD: str = Field(default="", description="Mot de passe SFTP Mirth")
    MIRTH_SFTP_PATH: str = Field(default="/hl7/incoming", description="Répertoire dépôt SFTP Mirth")

    # ═══════════════════════════════════════════════════════════════
    # AZURE COGNITIVE SERVICES (STT + TTS)
    # ═══════════════════════════════════════════════════════════════
    AZURE_SPEECH_KEY: str = Field(default="", description="Azure Cognitive Services Speech API Key")
    AZURE_SPEECH_REGION: str = Field(default="westeurope", description="Azure region (westeurope, francecentral)")
    AZURE_TTS_VOICE: str = Field(default="fr-BE-CharlineNeural", description="Azure Neural TTS voice (belge féminine)")
    AZURE_STT_LANGUAGE: str = Field(default="fr-BE", description="Azure STT language code")

    # Azure OpenAI (fallback LLM)
    AZURE_OPENAI_ENDPOINT: str = Field(default="", description="Azure OpenAI endpoint URL (ex: https://<resource>.openai.azure.com)")
    AZURE_OPENAI_API_KEY: str = Field(default="", description="Azure OpenAI API key")
    AZURE_OPENAI_DEPLOYMENT: str = Field(default="gpt-4o-mini", description="Azure OpenAI deployment name")

    # ═══════════════════════════════════════════════════════════════
    # MISTRAL API (LLM principal pour analyse médicale)
    # ═══════════════════════════════════════════════════════════════
    MISTRAL_API_KEY: str = Field(default="", description="Mistral API key (api.mistral.ai)")
    MISTRAL_MODEL: str = Field(default="mistral-small-latest", description="Modèle Mistral à utiliser")
    MISTRAL_BASE_URL: str = Field(default="https://api.mistral.ai/v1", description="URL de base de l'API Mistral")

    # ═══════════════════════════════════════════════════════════════
    # ASTERISK ARI (téléphonie)
    # ═══════════════════════════════════════════════════════════════
    ASTERISK_ARI_URL: str = Field(default="http://localhost:8088", description="URL de l'API REST Asterisk (ARI)")
    ASTERISK_ARI_USER: str = Field(default="hellojadeapp", description="Utilisateur ARI")
    ASTERISK_ARI_PASSWORD: str = Field(default="", description="Mot de passe ARI")
    ASTERISK_ARI_APP: str = Field(default="hellojadeapp", description="Nom de l'application Stasis ARI")
    ASTERISK_CALLER_NUMBER: str = Field(default="", description="Numéro d'appelant (format E.164, assigné par OVH)")
    ASTERISK_TRUNK: str = Field(default="ovh-sip", description="Nom du trunk SIP OVH dans pjsip.conf")

    # Transfert d'alerte
    TRANSFER_NUMBER: str = Field(default="", description="Numéro de l'équipe infirmières pour transfert d'alerte (E.164)")
    TRANSFER_MODE: str = Field(default="simulate", description="Mode transfert: real | simulate | disabled")
    # Si True, la parole du patient coupe la lecture TTS (bienvenue / question)
    VOICE_BARGE_IN_ENABLED: bool = Field(default=True, env="VOICE_BARGE_IN_ENABLED")

    # ═══════════════════════════════════════════════════════════════
    # BACKUP CONFIGURATION (Epicura)
    # ═══════════════════════════════════════════════════════════════
    BACKUP_ENABLED: bool = True
    BACKUP_RETENTION_DAYS: int = 30
    BACKUP_SCHEDULE: str = "0 2 * * *"  # Tous les jours à 2h du matin (cron)

    # ═══════════════════════════════════════════════════════════════
    # SIMULATION E2E (NE JAMAIS ACTIVER EN PRODUCTION)
    # Active les endpoints /api/v1/sim/* et les raccourcis de test.
    # ═══════════════════════════════════════════════════════════════
    SIMULATION_MODE: bool = Field(
        default=False,
        description="Active le mode simulation E2E (dev/test uniquement, JAMAIS en production)",
    )
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Créer les répertoires nécessaires
        for path in [self.LOG_FILE_PATH, self.REPORTS_PATH, self.DOCUMENTS_PATH, self.TEMP_PATH, self.RECORDINGS_PATH]:
            try:
                path.mkdir(parents=True, exist_ok=True)
            except (FileExistsError, PermissionError) as e:
                # Le chemin existe déjà (peut-être un fichier) ou permission refusée
                # L'entrypoint script devrait avoir créé les répertoires avec les bonnes permissions
                # Si l'erreur persiste, c'est un problème de configuration Docker
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Impossible de créer le répertoire {path}: {e}. "
                             f"Vérifiez que l'entrypoint script a créé les répertoires avec les bonnes permissions.")
                # Vérifier si le répertoire existe quand même
                if not path.exists():
                    raise


@lru_cache()
def get_settings() -> Settings:
    """Retourne une instance cachée des settings"""
    return Settings()


# Instance globale des settings
settings = get_settings()
