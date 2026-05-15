"""
Script pour corriger le statut des appels terminés qui sont encore marqués "en cours"
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime, UTC

# Ajouter le répertoire parent au path pour les imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.call import Call


async def fix_call_statuses():
    """Corrige le statut des appels qui devraient être terminés"""
    db_url = str(settings.DATABASE_URL)
    engine = create_async_engine(db_url, echo=False)
    
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async with async_session() as session:
        try:
            # Trouver tous les appels récents (dernières 24h)
            from datetime import timedelta
            recent_time = datetime.now(UTC) - timedelta(hours=24)
            stmt = select(Call).where(
                Call.created_at >= recent_time
            ).order_by(Call.created_at.desc())
            result = await session.execute(stmt)
            calls = result.scalars().all()
            
            print(f"📞 {len(calls)} appel(s) trouvé(s) dans les dernières 24h\n")
            
            fixed_count = 0
            for call in calls:
                # Afficher les détails de l'appel
                call_id_str = str(call.id)
                print(f"📞 Appel {call_id_str[:8]}...")
                print(f"   Statut: {call.status}")
                print(f"   Start: {call.start_time}")
                print(f"   Answer: {call.answer_time}")
                print(f"   End: {call.end_time}")
                print(f"   Durée: {call.duration}s")
                
                should_fix = False
                
                # Si l'appel a un end_time mais n'est pas marqué completed
                if call.end_time and call.status != "completed":
                    should_fix = True
                    print(f"   ⚠️  A un end_time mais statut = {call.status}")
                
                # Si l'appel est ancien (plus de 5 minutes) et toujours en cours sans end_time
                elif call.start_time and call.status in ["in_progress", "ringing", "pending"] and not call.end_time:
                    time_diff = (datetime.now(UTC) - call.start_time.replace(tzinfo=UTC)).total_seconds()
                    if time_diff > 300:  # 5 minutes
                        should_fix = True
                        print(f"   ⚠️  Ancien ({int(time_diff/60)} min) mais statut = {call.status} sans end_time")
                
                if should_fix:
                    old_status = call.status
                    call.status = "completed"
                    
                    # Mettre à jour end_time et duration si nécessaire
                    if not call.end_time:
                        call.end_time = datetime.now(UTC)
                    
                    if call.start_time and not call.duration:
                        duration = (call.end_time - call.start_time.replace(tzinfo=UTC)).total_seconds()
                        call.duration = int(duration)
                    
                    fixed_count += 1
                    print(f"  ✅ Corrigé: {old_status} → completed (durée: {call.duration}s)")
            
            if fixed_count > 0:
                await session.commit()
                print(f"\n✅ {fixed_count} appel(s) corrigé(s)")
            else:
                print("\n✅ Aucun appel à corriger")
                
        except Exception as e:
            print(f"❌ Erreur: {e}")
            await session.rollback()
            raise
    await engine.dispose()


async def main():
    """Fonction principale"""
    print("=" * 60)
    print("🔧 CORRECTION DU STATUT DES APPELS")
    print("=" * 60)
    print()
    
    await fix_call_statuses()
    
    print()
    print("=" * 60)
    print("✅ TERMINÉ")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

