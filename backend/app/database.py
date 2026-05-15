"""
Configuration de la base de données avec SQLAlchemy 2.0
"""
from typing import AsyncGenerator, Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


# Base pour les modèles SQLAlchemy
class Base(DeclarativeBase):
    """Classe de base pour tous les modèles SQLAlchemy"""
    pass


# Moteur asynchrone pour PostgreSQL (application)
async_engine = create_async_engine(
    str(settings.DATABASE_URL),
    echo=settings.DEBUG and settings.ENVIRONMENT == "development",
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=10,
    pool_recycle=3600,
    pool_timeout=30,
)


# Session factory asynchrone
AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# Moteur synchrone pour PostgreSQL (Celery tasks)
# Utilise psycopg3 (pas psycopg2) pour la compatibilité avec SQLAlchemy 2.0
sync_engine = create_engine(
    str(settings.DATABASE_URL).replace("+asyncpg", "+psycopg"),
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    pool_recycle=3600,
)

# Session factory synchrone pour Celery
SyncSessionLocal = sessionmaker(
    sync_engine,
    class_=Session,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# Dependency pour obtenir la session DB
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency pour obtenir une session de base de données PostgreSQL
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()



async def init_db() -> None:
    """
    Initialise la base de données
    Crée les tables si elles n'existent pas
    """
    async with async_engine.begin() as conn:
        # Import tous les modèles pour qu'ils soient enregistrés
        from app.models import (  # noqa: F401
            analysis,
            audit_log,
            call,
            care_unit,
            document,
            patient,
            questionnaire,
            report,
            setting,
            transcription,
            user,
        )
        
        # Créer toutes les tables
        await conn.run_sync(Base.metadata.create_all)


async def drop_db() -> None:
    """
    Supprime toutes les tables de la base de données
    À utiliser avec précaution !
    """
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
