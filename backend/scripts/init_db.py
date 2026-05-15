#!/usr/bin/env python3
"""
Script d'initialisation de la base de données HelloJADE

Ce script :
1. Vérifie la connexion à la base de données
2. Applique les migrations Alembic
3. Crée l'utilisateur admin par défaut (si demandé)

Usage:
    python scripts/init_db.py [--create-admin]
"""
import asyncio
import sys
from pathlib import Path

# Ajouter le répertoire parent au path pour les imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings
from app.core.logging import get_logger
from app.database import async_engine, init_db
from sqlalchemy import text

logger = get_logger(__name__)


async def check_database_connection():
    """Vérifie que la connexion à la base de données fonctionne"""
    try:
        async with async_engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            result.scalar()
            logger.info("✅ Connexion à la base de données réussie")
            return True
    except Exception as e:
        logger.error(f"❌ Erreur de connexion à la base de données: {e}")
        return False


async def run_migrations():
    """Applique les migrations Alembic"""
    try:
        import subprocess
        import os
        
        # Changer vers le répertoire backend
        backend_dir = Path(__file__).parent.parent
        os.chdir(backend_dir)
        
        # Exécuter alembic upgrade head
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
        )
        
        if result.returncode == 0:
            logger.info("✅ Migrations appliquées avec succès")
            if result.stdout:
                logger.debug(result.stdout)
            return True
        else:
            logger.error(f"❌ Erreur lors de l'application des migrations:")
            logger.error(result.stderr)
            return False
            
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'exécution des migrations: {e}")
        return False


async def create_tables_directly():
    """
    Crée les tables directement via SQLAlchemy (fallback si Alembic échoue)
    """
    try:
        logger.info("Création des tables directement...")
        await init_db()
        logger.info("✅ Tables créées avec succès")
        return True
    except Exception as e:
        logger.error(f"❌ Erreur lors de la création des tables: {e}")
        return False


async def main(create_admin: bool = False):
    """Fonction principale"""
    logger.info("=" * 60)
    logger.info("🏥 Initialisation de la base de données HelloJADE")
    logger.info("=" * 60)
    logger.info(f"Environnement: {settings.ENVIRONMENT}")
    logger.info(f"Base de données: {settings.POSTGRES_DB} @ {settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}")
    logger.info("")
    
    # 1. Vérifier la connexion
    logger.info("1️⃣  Vérification de la connexion...")
    if not await check_database_connection():
        logger.error("❌ Impossible de se connecter à la base de données")
        logger.error("   Vérifiez vos paramètres dans .env (POSTGRES_HOST, POSTGRES_PORT, etc.)")
        sys.exit(1)
    
    # 2. Appliquer les migrations
    logger.info("")
    logger.info("2️⃣  Application des migrations Alembic...")
    migrations_success = await run_migrations()
    
    if not migrations_success:
        logger.warning("⚠️  Les migrations Alembic ont échoué, tentative de création directe...")
        if not await create_tables_directly():
            logger.error("❌ Échec de la création des tables")
            sys.exit(1)
    
    # 3. Créer l'utilisateur admin si demandé
    if create_admin:
        logger.info("")
        logger.info("3️⃣  Création de l'utilisateur admin...")
        try:
            from scripts.create_admin import create_default_admin
            await create_default_admin()
        except Exception as e:
            logger.error(f"❌ Erreur lors de la création de l'admin: {e}")
            logger.warning("   Vous pourrez créer l'admin manuellement plus tard")
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("✅ Initialisation terminée avec succès !")
    logger.info("=" * 60)
    
    if create_admin:
        logger.info("")
        logger.info("📧 Identifiants admin par défaut:")
        logger.info("   Email: admin@hellojadeapp.com")
        logger.info("   Mot de passe: admin123")
        logger.info("   ⚠️  CHANGEZ LE MOT DE PASSE IMMÉDIATEMENT !")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Initialiser la base de données HelloJADE")
    parser.add_argument(
        "--create-admin",
        action="store_true",
        help="Créer l'utilisateur admin par défaut",
    )
    
    args = parser.parse_args()
    
    asyncio.run(main(create_admin=args.create_admin))

