#!/usr/bin/env python3
"""
Script de backup PostgreSQL pour HelloJADE Epicura.

Ce script :
- Effectue un pg_dump complet de la base PostgreSQL
- Sauvegarde le dump dans le répertoire configuré (monté depuis SMB)
- Gère la rotation des backups (rétention configurable)
- Log les opérations pour suivi

Usage:
    python scripts/backup_postgres.py
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Ajouter le répertoire parent au path pour importer app.core.config
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def get_backup_path() -> Path:
    """Retourne le chemin du répertoire de backup."""
    backup_path = Path(settings.BACKUP_PATH)
    backup_path.mkdir(parents=True, exist_ok=True)
    return backup_path


def cleanup_old_backups(backup_dir: Path, retention_days: int = 30) -> int:
    """
    Supprime les backups plus anciens que retention_days.
    
    Args:
        backup_dir: Répertoire contenant les backups
        retention_days: Nombre de jours de rétention
        
    Returns:
        Nombre de fichiers supprimés
    """
    if not backup_dir.exists():
        return 0
    
    cutoff_date = datetime.now() - timedelta(days=retention_days)
    deleted_count = 0
    
    for backup_file in backup_dir.glob("hellojadeapp_*.dump"):
        try:
            # Extraire la date du nom de fichier (format: hellojadeapp_YYYYMMDD_HHMMSS.dump)
            parts = backup_file.stem.split("_")
            if len(parts) >= 3:
                date_str = f"{parts[1]}_{parts[2]}"
                file_date = datetime.strptime(date_str, "%Y%m%d_%H%M%S")
                
                if file_date < cutoff_date:
                    backup_file.unlink()
                    logger.info(f"🗑️  Backup supprimé (rétention): {backup_file.name}")
                    deleted_count += 1
        except (ValueError, IndexError) as e:
            logger.warning(f"Impossible de parser la date du fichier {backup_file.name}: {e}")
            # Si on ne peut pas parser, on garde le fichier par sécurité
    
    return deleted_count


def perform_backup() -> Optional[str]:
    """
    Effectue un backup complet de PostgreSQL.
    
    Returns:
        Chemin du fichier de backup créé, ou None en cas d'erreur
    """
    # Récupérer les credentials depuis les variables d'environnement
    db_host = os.getenv("POSTGRES_HOST", "postgres")
    db_port = os.getenv("POSTGRES_PORT", "5432")
    db_name = os.getenv("POSTGRES_DB", "hellojadeapp")
    db_user = os.getenv("POSTGRES_USER", "hellojadeapp")
    db_password = os.getenv("POSTGRES_PASSWORD")
    
    if not db_password:
        logger.error("❌ POSTGRES_PASSWORD non défini. Impossible de faire le backup.")
        return None
    
    # Créer le nom de fichier avec timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"hellojadeapp_{timestamp}.dump"
    backup_path = get_backup_path()
    backup_file = backup_path / backup_filename
    
    # Commande pg_dump
    # Format custom (-Fc) pour compression et restauration flexible
    pg_dump_cmd = [
        "pg_dump",
        "-h", db_host,
        "-p", str(db_port),
        "-U", db_user,
        "-d", db_name,
        "-Fc",  # Format custom (compressé)
        "-f", str(backup_file),
    ]
    
    # Définir PGPASSWORD pour éviter la prompt interactive
    env = os.environ.copy()
    env["PGPASSWORD"] = db_password
    
    logger.info(f"🔄 Démarrage du backup PostgreSQL vers: {backup_file}")
    
    try:
        import subprocess
        result = subprocess.run(
            pg_dump_cmd,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        
        # Vérifier que le fichier a bien été créé
        if backup_file.exists():
            file_size_mb = backup_file.stat().st_size / (1024 * 1024)
            logger.info(f"✅ Backup réussi: {backup_filename} ({file_size_mb:.2f} MB)")
            return str(backup_file)
        else:
            logger.error(f"❌ Le fichier de backup n'a pas été créé: {backup_file}")
            return None
            
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Erreur lors du backup PostgreSQL: {e}")
        logger.error(f"   stdout: {e.stdout}")
        logger.error(f"   stderr: {e.stderr}")
        return None
    except Exception as e:
        logger.error(f"❌ Erreur inattendue lors du backup: {e}")
        return None


def main():
    """Point d'entrée principal."""
    logger.info("=" * 60)
    logger.info("🚀 Démarrage du backup PostgreSQL HelloJADE Epicura")
    logger.info("=" * 60)
    
    # Effectuer le backup
    backup_file = perform_backup()
    
    if not backup_file:
        logger.error("❌ Échec du backup. Arrêt.")
        sys.exit(1)
    
    # Nettoyer les anciens backups
    retention_days = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))
    backup_dir = get_backup_path()
    deleted_count = cleanup_old_backups(backup_dir, retention_days)
    
    if deleted_count > 0:
        logger.info(f"🗑️  {deleted_count} ancien(s) backup(s) supprimé(s)")
    
    logger.info("=" * 60)
    logger.info("✅ Backup terminé avec succès")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
