"""
Script pour supprimer les appels avec le statut "interrupted" de la base de données.

⚠️ ATTENTION : Ce script SUPPRIME DÉFINITIVEMENT les appels de la base de données.
Utilisez --dry-run pour prévisualiser avant de supprimer.
"""
import asyncio
import sys
from pathlib import Path

# Ajouter le répertoire parent au path pour les imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.call import Call


async def cleanup_interrupted_calls(dry_run: bool = False):
    """
    Supprime tous les appels avec le statut "interrupted".
    
    Args:
        dry_run: Si True, affiche seulement ce qui serait fait sans supprimer (défaut: False)
    """
    db_url = str(settings.DATABASE_URL)
    engine = create_async_engine(db_url, echo=False)
    
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async with async_session() as session:
        try:
            # Trouver tous les appels avec le statut "interrupted"
            stmt = select(Call).where(
                Call.status == "interrupted"
            ).order_by(Call.created_at.desc())
            
            result = await session.execute(stmt)
            interrupted_calls = result.scalars().all()
            
            print("=" * 70)
            print("🗑️  SUPPRESSION DES APPELS INTERRUPTED")
            print("=" * 70)
            print(f"\n📊 Critères de recherche :")
            print(f"   - Statut : interrupted")
            print(f"\n🔍 {len(interrupted_calls)} appel(s) 'interrupted' trouvé(s)\n")
            
            if not interrupted_calls:
                print("✅ Aucun appel 'interrupted' à supprimer")
                await engine.dispose()
                return
            
            deleted_count = 0
            for call in interrupted_calls:
                # Afficher les détails
                call_id_str = str(call.id)[:8]
                print(f"📞 Appel {call_id_str}...")
                print(f"   Statut actuel : {call.status}")
                print(f"   Créé le       : {call.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
                if call.start_time:
                    print(f"   Démarré le    : {call.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
                if call.end_time:
                    print(f"   Terminé le    : {call.end_time.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"   Patient       : {call.patient_id}")
                
                if dry_run:
                    print(f"   ⚠️  [DRY RUN] Serait SUPPRIMÉ")
                else:
                    # Supprimer l'appel (les relations seront supprimées en cascade selon le modèle)
                    await session.delete(call)
                    deleted_count += 1
                    print(f"   🗑️  SUPPRIMÉ")
                
                print()
            
            if not dry_run and deleted_count > 0:
                await session.commit()
                print("=" * 70)
                print(f"✅ {deleted_count} appel(s) supprimé(s) avec succès")
                print("=" * 70)
            elif dry_run:
                print("=" * 70)
                print(f"⚠️  MODE DRY RUN : Aucune suppression effectuée")
                print(f"   {len(interrupted_calls)} appel(s) seraient supprimés")
                print("=" * 70)
            else:
                print("=" * 70)
                print("✅ Aucun appel supprimé")
                print("=" * 70)
                
        except Exception as e:
            print(f"\n❌ Erreur lors de la suppression: {e}")
            import traceback
            traceback.print_exc()
            await session.rollback()
            raise
    await engine.dispose()


async def main():
    """Fonction principale"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Supprime tous les appels avec le statut 'interrupted' de la base de données"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche seulement ce qui serait fait sans supprimer (recommandé avant suppression réelle)"
    )
    
    args = parser.parse_args()
    
    if args.dry_run:
        print("\n⚠️  MODE DRY RUN ACTIVÉ - Aucune suppression ne sera effectuée\n")
    else:
        print("\n⚠️  ATTENTION : Les appels 'interrupted' seront SUPPRIMÉS DÉFINITIVEMENT de la base de données")
        print("   Utilisez --dry-run pour prévisualiser avant de supprimer\n")
    
    await cleanup_interrupted_calls(dry_run=args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())

