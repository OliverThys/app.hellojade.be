"""
Script pour supprimer un appel de la base de données.
Usage: python -m scripts.delete_call <call_id>
"""
import asyncio
import sys
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.call import Call


async def delete_call(call_id_str: str):
    """Supprime un appel et toutes ses relations (transcription, analysis, reports)"""
    try:
        call_id = UUID(call_id_str)
    except ValueError:
        print(f"❌ ID d'appel invalide: {call_id_str}")
        print("   Format attendu: UUID (ex: bc647dac-b04c-4a61-ac47-c8e292cc2b26)")
        return

    async with AsyncSessionLocal() as session:
        try:
            # Récupérer l'appel avec ses relations
            result = await session.execute(
                select(Call).where(Call.id == call_id)
            )
            call = result.scalar_one_or_none()

            if not call:
                print(f"❌ Appel {call_id} non trouvé dans la base de données")
                return

            # Afficher les informations de l'appel avant suppression
            print(f"\n📞 Appel trouvé:")
            print(f"   ID: {call.id}")
            print(f"   Patient: {call.patient_id}")
            print(f"   Statut: {call.status}")
            print(f"   Date: {call.start_time or call.created_at}")
            print(f"   Durée: {call.duration}s" if call.duration else "   Durée: N/A")
            print(f"   Transcription: {'Oui' if call.transcription else 'Non'}")
            print(f"   Analyse: {'Oui' if call.analysis else 'Non'}")
            print(f"   Reports: {len(call.reports) if call.reports else 0}")

            # Confirmation
            print(f"\n⚠️  Êtes-vous sûr de vouloir supprimer cet appel ?")
            print(f"   Cela supprimera également:")
            print(f"   - La transcription (si présente)")
            print(f"   - L'analyse IA (si présente)")
            print(f"   - Les rapports associés (si présents)")
            
            # Pour un script CLI, on peut demander confirmation
            # Mais pour l'instant, on supprime directement
            # response = input("\n   Tapez 'OUI' pour confirmer: ")
            # if response != 'OUI':
            #     print("❌ Suppression annulée")
            #     return

            # Supprimer l'appel (les relations seront supprimées en cascade)
            await session.delete(call)
            await session.commit()

            print(f"\n✅ Appel {call_id} supprimé avec succès")
            print(f"   Transcription, analyse et rapports associés ont également été supprimés")

        except Exception as e:
            await session.rollback()
            print(f"❌ Erreur lors de la suppression: {e}")
            import traceback
            traceback.print_exc()


async def main():
    """Point d'entrée principal"""
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.delete_call <call_id>")
        print("\nExemple:")
        print("  python -m scripts.delete_call bc647dac-b04c-4a61-ac47-c8e292cc2b26")
        sys.exit(1)

    call_id = sys.argv[1]
    await delete_call(call_id)


if __name__ == "__main__":
    asyncio.run(main())

