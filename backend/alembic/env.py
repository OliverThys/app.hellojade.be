"""
Configuration Alembic pour les migrations de base de données
"""
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import des modèles et de la configuration
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from app.core.config import settings
from app.database import Base

# Import tous les modèles pour qu'ils soient enregistrés
from app.models import (  # noqa: F401
    user,
    patient,
    call,
    transcription,
    analysis,
    report,
    audit_log,
    setting,
    questionnaire,
)

# Configuration Alembic
config = context.config

# Configuration du logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Métadonnées pour l'auto-génération
target_metadata = Base.metadata

# Configuration de la base de données
config.set_main_option("sqlalchemy.url", str(settings.DATABASE_URL))


def run_migrations_offline() -> None:
    """
    Exécute les migrations en mode 'offline'.
    
    Ceci configure le contexte avec juste une URL
    et sans Engine, mais n'exécute pas de connexion.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """
    Fonction helper pour exécuter les migrations
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Exécute les migrations en mode asynchrone
    """
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = str(settings.DATABASE_URL)
    
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """
    Exécute les migrations en mode 'online'.
    
    Crée un Engine et associe une connexion avec le contexte.
    """
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

