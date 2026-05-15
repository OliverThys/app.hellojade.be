#!/usr/bin/env python3
"""
Script pour créer l'utilisateur administrateur par défaut

Ce script crée un utilisateur admin avec les identifiants :
- Email: admin@hellojadeapp.com
- Username: admin
- Password: admin123

⚠️ IMPORTANT: Changez le mot de passe après la première connexion !

Usage:
    python scripts/create_admin.py [--email EMAIL] [--username USERNAME] [--password PASSWORD]
"""
import asyncio
import sys
from pathlib import Path

# Ajouter le répertoire parent au path pour les imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import get_password_hash
from app.database import AsyncSessionLocal
from app.models.user import User

logger = get_logger(__name__)


async def create_default_admin(
    email: str = "admin@hellojadeapp.com",
    username: str = "admin",
    password: str = "admin123",
    full_name: str = "Administrateur HelloJADE",
) -> User:
    """
    Crée l'utilisateur administrateur par défaut
    
    Args:
        email: Email de l'administrateur
        username: Nom d'utilisateur
        password: Mot de passe (sera hashé)
        full_name: Nom complet
    
    Returns:
        Utilisateur créé
    
    Raises:
        Exception: Si l'utilisateur existe déjà ou en cas d'erreur
    """
    async with AsyncSessionLocal() as session:
        try:
            # Vérifier si un admin existe déjà
            stmt = select(User).where(User.email == email)
            result = await session.execute(stmt)
            existing_user = result.scalar_one_or_none()
            
            if existing_user:
                logger.warning(f"⚠️  L'utilisateur avec l'email {email} existe déjà")
                logger.info(f"   ID: {existing_user.id}")
                logger.info(f"   Username: {existing_user.username}")
                logger.info(f"   Role: {existing_user.role}")
                
                # Demander confirmation pour mettre à jour
                response = input("\nVoulez-vous mettre à jour cet utilisateur ? (o/N): ")
                if response.lower() != 'o':
                    logger.info("   Opération annulée")
                    return existing_user
                
                # Mettre à jour l'utilisateur existant
                existing_user.username = username
                existing_user.hashed_password = get_password_hash(password)
                existing_user.full_name = full_name
                existing_user.role = "admin"
                existing_user.is_active = True
                
                await session.commit()
                await session.refresh(existing_user)
                
                logger.info("✅ Utilisateur mis à jour avec succès")
                return existing_user
            
            # Créer le nouvel utilisateur admin
            admin_user = User(
                email=email,
                username=username,
                hashed_password=get_password_hash(password),
                full_name=full_name,
                role="admin",
                is_active=True,
            )
            
            session.add(admin_user)
            await session.commit()
            await session.refresh(admin_user)
            
            logger.info("✅ Utilisateur administrateur créé avec succès")
            logger.info(f"   ID: {admin_user.id}")
            logger.info(f"   Email: {admin_user.email}")
            logger.info(f"   Username: {admin_user.username}")
            logger.info(f"   Role: {admin_user.role}")
            
            return admin_user
            
        except Exception as e:
            await session.rollback()
            logger.error(f"❌ Erreur lors de la création de l'administrateur: {e}")
            raise


async def main():
    """Fonction principale"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Créer l'utilisateur administrateur par défaut",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  # Créer avec les valeurs par défaut
  python scripts/create_admin.py
  
  # Créer avec des identifiants personnalisés
  python scripts/create_admin.py --email admin@example.com --username monadmin --password MonMotDePasse123!
        """
    )
    
    parser.add_argument(
        "--email",
        type=str,
        default="admin@hellojadeapp.com",
        help="Email de l'administrateur (défaut: admin@hellojadeapp.com)",
    )
    parser.add_argument(
        "--username",
        type=str,
        default="admin",
        help="Nom d'utilisateur (défaut: admin)",
    )
    parser.add_argument(
        "--password",
        type=str,
        default="admin123",
        help="Mot de passe (défaut: admin123) ⚠️ À CHANGER !",
    )
    parser.add_argument(
        "--full-name",
        type=str,
        default="Administrateur HelloJADE",
        help="Nom complet (défaut: Administrateur HelloJADE)",
    )
    
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("👤 Création de l'utilisateur administrateur")
    logger.info("=" * 60)
    
    try:
        user = await create_default_admin(
            email=args.email,
            username=args.username,
            password=args.password,
            full_name=args.full_name,
        )
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("✅ Utilisateur administrateur créé/mis à jour avec succès")
        logger.info("=" * 60)
        logger.info("")
        logger.info("📧 Identifiants:")
        logger.info(f"   Email: {user.email}")
        logger.info(f"   Username: {user.username}")
        logger.info(f"   Password: {args.password}")
        logger.info("")
        logger.warning("⚠️  IMPORTANT: Changez le mot de passe après la première connexion !")
        
    except Exception as e:
        logger.error(f"❌ Échec de la création de l'administrateur: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

