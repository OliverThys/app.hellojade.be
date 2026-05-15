"""
Configuration du système de logging
"""
import json
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any, Dict

from pythonjsonlogger import jsonlogger

from app.core.config import settings


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """Formateur JSON personnalisé pour les logs"""
    
    def add_fields(
        self,
        log_record: Dict[str, Any],
        record: logging.LogRecord,
        message_dict: Dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        
        # Ajouter des champs personnalisés
        log_record["timestamp"] = self.formatTime(record)
        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        log_record["module"] = record.module
        log_record["function"] = record.funcName
        log_record["line"] = record.lineno
        
        # Ajouter l'environnement et la version
        log_record["environment"] = settings.ENVIRONMENT
        log_record["app_version"] = settings.VERSION
        
        # Ajouter l'exception si présente
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)


def setup_logging() -> logging.Logger:
    """
    Configure le système de logging pour l'application
    
    Returns:
        Logger configuré
    """
    # Créer le logger principal
    logger = logging.getLogger("hellojadeapp")
    logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper()))
    
    # Supprimer les handlers existants
    logger.handlers.clear()
    
    # Handler console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, settings.LOG_LEVEL.upper()))
    
    # Format selon l'environnement
    if settings.LOG_FORMAT == "json":
        formatter = CustomJsonFormatter(
            "%(timestamp)s %(level)s %(name)s %(message)s",
            timestamp=True,
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Handler fichier (si configuré)
    if settings.LOG_FILE_PATH:
        log_file = settings.LOG_FILE_PATH / "hellojadeapp.log"
        try:
            # Vérifier si le parent existe et est un répertoire
            if log_file.parent.exists():
                if log_file.parent.is_dir():
                    # C'est un répertoire, créer le handler
                    file_handler = logging.handlers.RotatingFileHandler(
                        log_file,
                        maxBytes=100 * 1024 * 1024,  # 100MB
                        backupCount=10,
                        encoding="utf-8",
                    )
                    file_handler.setLevel(getattr(logging, settings.LOG_LEVEL.upper()))
                    file_handler.setFormatter(formatter)
                    logger.addHandler(file_handler)
            else:
                # Le répertoire n'existe pas, essayer de le créer
                try:
                    log_file.parent.mkdir(parents=True, exist_ok=True)
                    file_handler = logging.handlers.RotatingFileHandler(
                        log_file,
                        maxBytes=100 * 1024 * 1024,  # 100MB
                        backupCount=10,
                        encoding="utf-8",
                    )
                    file_handler.setLevel(getattr(logging, settings.LOG_LEVEL.upper()))
                    file_handler.setFormatter(formatter)
                    logger.addHandler(file_handler)
                except (FileExistsError, OSError):
                    # Impossible de créer le répertoire, ignorer
                    pass
        except Exception:
            # En cas d'erreur, continuer sans handler fichier
            pass
    
    # Configurer les loggers des librairies tierces
    
    # SQLAlchemy
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DEBUG else logging.WARNING
    )
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    
    # Uvicorn
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    
    # FastAPI
    logging.getLogger("fastapi").setLevel(logging.INFO)
    
    # Celery
    logging.getLogger("celery").setLevel(logging.INFO)
    
    # Désactiver les logs trop verbeux
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("multipart").setLevel(logging.WARNING)
    
    logger.info(
        f"Logging configuré - Niveau: {settings.LOG_LEVEL}, "
        f"Format: {settings.LOG_FORMAT}, "
        f"Environnement: {settings.ENVIRONMENT}"
    )
    
    return logger


# Logger global pour l'application
logger = setup_logging()


def get_logger(name: str) -> logging.Logger:
    """
    Obtient un logger pour un module spécifique
    
    Args:
        name: Nom du module
    
    Returns:
        Logger configuré
    """
    return logging.getLogger(f"hellojadeapp.{name}")
