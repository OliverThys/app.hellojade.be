"""
Script pour nettoyer les appels et créer des patients de test
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
from app.models.patient import Patient
from app.models.transcription import Transcription
from app.models.analysis import Analysis
from datetime import datetime, date, UTC


async def cleanup_calls():
    """Supprime tous les appels de la base de données"""
    # Convertir l'URL en string si nécessaire
    db_url = str(settings.DATABASE_URL)
    engine = create_async_engine(
        db_url,
        echo=False,
    )
    
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async with async_session() as session:
        try:
            # Supprimer les transcriptions et analyses liées
            print("🗑️  Suppression des transcriptions...")
            await session.execute(delete(Transcription))
            
            print("🗑️  Suppression des analyses...")
            await session.execute(delete(Analysis))
            
            print("🗑️  Suppression des appels...")
            await session.execute(delete(Call))
            
            await session.commit()
            print("✅ Tous les appels ont été supprimés")
        except Exception as e:
            print(f"❌ Erreur lors du nettoyage: {e}")
            await session.rollback()
            raise
    await engine.dispose()


async def create_test_patients():
    """Crée les patients de test"""
    # Convertir l'URL en string si nécessaire
    db_url = str(settings.DATABASE_URL)
    engine = create_async_engine(
        db_url,
        echo=False,
    )
    
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async with async_session() as session:
        try:
            # Vérifier si les patients existent déjà
            from sqlalchemy import select
            
            # Patient 1: Oliver Thys
            stmt = select(Patient).where(Patient.telephone == "0471034785")
            result = await session.execute(stmt)
            oliver = result.scalar_one_or_none()
            
            if not oliver:
                # Vérifier aussi par oracle_patient_id
                stmt = select(Patient).where(Patient.oracle_patient_id == 1001)
                result = await session.execute(stmt)
                oliver = result.scalar_one_or_none()
            
            if not oliver:
                oliver = Patient(
                    oracle_patient_id=1001,
                    numero_dossier="THY-2024-001",
                    nom="Thys",
                    prenom="Oliver",
                    telephone="0471034785",
                    email="oliver.thys@example.com",
                    date_naissance=date(1985, 6, 15),
                    sexe="M",
                    adresse="Rue de la Santé 42",
                    ville="Bruxelles",
                    code_postal="1000",
                    service_hospitalisation="Chirurgie générale",
                    date_admission=date(2024, 11, 20),
                    date_sortie=date(2024, 11, 25),
                    diagnostic_principal="Appendicectomie",
                    medecin_responsable="Dr. Martin Dubois",
                    status="actif",
                    risk_score=3,
                    consent_given=True,
                    consent_date=datetime.now(UTC),
                    notes="Patient coopératif, bon suivi post-opératoire",
                )
                session.add(oliver)
                print("✅ Patient Oliver Thys créé")
            else:
                # Mettre à jour le patient existant
                oliver.telephone = "0471034785"
                oliver.nom = "Thys"
                oliver.prenom = "Oliver"
                oliver.status = "actif"
                oliver.consent_given = True
                print("✅ Patient Oliver Thys mis à jour")
            
            # Patient 2: Andreas Bottiggi
            stmt = select(Patient).where(Patient.telephone == "0472201535")
            result = await session.execute(stmt)
            andreas = result.scalar_one_or_none()
            
            if not andreas:
                # Vérifier aussi par oracle_patient_id
                stmt = select(Patient).where(Patient.oracle_patient_id == 1002)
                result = await session.execute(stmt)
                andreas = result.scalar_one_or_none()
            
            if not andreas:
                andreas = Patient(
                    oracle_patient_id=1002,
                    numero_dossier="BOT-2024-002",
                    nom="Bottiggi",
                    prenom="Andreas",
                    telephone="0472201535",
                    email="andreas.bottiggi@example.com",
                    date_naissance=date(1992, 3, 22),
                    sexe="M",
                    adresse="Avenue des Fleurs 78",
                    ville="Liège",
                    code_postal="4000",
                    service_hospitalisation="Cardiologie",
                    date_admission=date(2024, 11, 18),
                    date_sortie=date(2024, 11, 23),
                    diagnostic_principal="Suivi post-infarctus",
                    medecin_responsable="Dr. Sophie Lambert",
                    status="actif",
                    risk_score=5,
                    consent_given=True,
                    consent_date=datetime.now(UTC),
                    notes="Surveillance cardiaque renforcée, traitement anticoagulant",
                )
                session.add(andreas)
                print("✅ Patient Andreas Bottiggi créé")
            else:
                # Mettre à jour le patient existant
                andreas.telephone = "0472201535"
                andreas.nom = "Bottiggi"
                andreas.prenom = "Andreas"
                andreas.status = "actif"
                andreas.consent_given = True
                print("✅ Patient Andreas Bottiggi mis à jour")
            
            await session.commit()
            print("✅ Patients de test créés avec succès")
        except Exception as e:
            print(f"❌ Erreur lors de la création des patients: {e}")
            await session.rollback()
            raise
    await engine.dispose()


async def main():
    """Fonction principale"""
    print("=" * 60)
    print("🧹 NETTOYAGE ET CONFIGURATION DE LA BASE DE DONNÉES")
    print("=" * 60)
    print()
    
    # Nettoyer les appels
    print("📞 Nettoyage des appels...")
    await cleanup_calls()
    print()
    
    # Créer les patients
    print("👥 Création des patients de test...")
    await create_test_patients()
    print()
    
    print("=" * 60)
    print("✅ TERMINÉ")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

