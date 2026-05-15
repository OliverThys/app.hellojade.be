"""
Script pour nettoyer uniquement les appels (sans créer de patients)
"""
import asyncio
import sys
from pathlib import Path

# Ajouter le répertoire parent au path pour les imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.call import Call
from app.models.transcription import Transcription
from app.models.analysis import Analysis


async def cleanup_calls():
    """Supprime tous les appels de la base de données"""
    # Convertir l'URL en string si nécessaire
    db_url = str(settings.DATABASE_URL)
    engine = create_async_engine(
        db_url,
        echo=False,
    )
    AsyncSessionLocal = sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    
    async with AsyncSessionLocal() as session:
        print("🗑️  Suppression des transcriptions...")
        await session.execute(delete(Transcription))
        print("🗑️  Suppression des analyses...")
        await session.execute(delete(Analysis))
        print("🗑️  Suppression des appels...")
        await session.execute(delete(Call))
        await session.commit()
    print("✅ Tous les appels ont été supprimés")


if __name__ == "__main__":
    asyncio.run(cleanup_calls())

