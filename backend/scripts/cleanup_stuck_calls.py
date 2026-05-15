"""
Script pour supprimer les appels restés "en cours" après des tests interrompus.

Ce script identifie et SUPPRIME les appels qui :
- Ont un statut "in_progress", "ringing" ou "pending"
- N'ont pas de end_time
- Sont anciens (plus de 10 minutes depuis start_time ou created_at)
- Ont probablement été coupés pendant les tests

⚠️ ATTENTION : Ce script SUPPRIME DÉFINITIVEMENT les appels de la base de données.
Il ne touche QUE les appels qui sont clairement bloqués et anciens.
Utilisez --dry-run pour prévisualiser avant de supprimer.
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta, UTC

# Ajouter le répertoire parent au path pour les imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.call import Call


async def cleanup_stuck_calls(min_age_minutes: int = 10, dry_run: bool = False):
    """
    Supprime les appels restés "en cours" après des tests interrompus.
    
    Args:
        min_age_minutes: Âge minimum en minutes pour considérer un appel comme bloqué (défaut: 10)
        dry_run: Si True, affiche seulement ce qui serait fait sans supprimer (défaut: False)
    """
    db_url = str(settings.DATABASE_URL)
    engine = create_async_engine(db_url, echo=False)
    
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async with async_session() as session:
        try:
            # Calculer le seuil de temps
            now = datetime.now(UTC)
            min_age = timedelta(minutes=min_age_minutes)
            threshold_time = now - min_age
            
            # Trouver les appels bloqués :
            # - Statut "in_progress", "ringing" ou "pending"
            # - Pas de end_time
            # - Soit start_time est ancien, soit created_at est ancien (si pas de start_time)
            stmt = select(Call).where(
                and_(
                    Call.status.in_(["in_progress", "ringing", "pending"]),
                    Call.end_time.is_(None),
                    or_(
                        and_(Call.start_time.isnot(None), Call.start_time <= threshold_time),
                        and_(Call.start_time.is_(None), Call.created_at <= threshold_time)
                    )
                )
            ).order_by(Call.created_at.desc())
            
            result = await session.execute(stmt)
            stuck_calls = result.scalars().all()
            
            print("=" * 70)
            print("🗑️  SUPPRESSION DES APPELS BLOQUÉS")
            print("=" * 70)
            print(f"\n📊 Critères de recherche :")
            print(f"   - Statut : in_progress, ringing, ou pending")
            print(f"   - Sans end_time")
            print(f"   - Âge minimum : {min_age_minutes} minutes")
            print(f"   - Seuil temporel : {threshold_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            print(f"\n🔍 {len(stuck_calls)} appel(s) bloqué(s) trouvé(s)\n")
            
            if not stuck_calls:
                print("✅ Aucun appel à supprimer")
                await engine.dispose()
                return
            
            deleted_count = 0
            for call in stuck_calls:
                # Calculer l'âge de l'appel
                reference_time = call.start_time if call.start_time else call.created_at
                if reference_time.tzinfo is None:
                    reference_time = reference_time.replace(tzinfo=UTC)
                age_seconds = (now - reference_time).total_seconds()
                age_minutes = int(age_seconds / 60)
                
                # Afficher les détails
                call_id_str = str(call.id)[:8]
                print(f"📞 Appel {call_id_str}...")
                print(f"   Statut actuel : {call.status}")
                print(f"   Créé le       : {call.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
                if call.start_time:
                    print(f"   Démarré le    : {call.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"   Âge           : {age_minutes} minutes")
                print(f"   Patient       : {call.patient_id}")
                
                # Vérifier si c'est un appel automatisé (via call_metadata)
                if call.call_metadata:
                    mode = call.call_metadata.get("mode")
                    if mode == "automated":
                        print(f"   Type          : Appel automatisé")
                
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
                print(f"   {len(stuck_calls)} appel(s) seraient supprimés")
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
        description="Supprime les appels restés 'en cours' après des tests interrompus"
    )
    parser.add_argument(
        "--min-age",
        type=int,
        default=10,
        help="Âge minimum en minutes pour considérer un appel comme bloqué (défaut: 10)"
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
        print("\n⚠️  ATTENTION : Les appels seront SUPPRIMÉS DÉFINITIVEMENT de la base de données")
        print("   Utilisez --dry-run pour prévisualiser avant de supprimer\n")
    
    await cleanup_stuck_calls(
        min_age_minutes=args.min_age,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    asyncio.run(main())

