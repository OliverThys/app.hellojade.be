#!/usr/bin/env python3
"""
Script pour créer des patients spécifiques dans la base de données

Usage:
    python scripts/create_patients.py
"""
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Ajouter le répertoire parent au path pour les imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database import AsyncSessionLocal
from app.models.patient import Patient

logger = get_logger(__name__)


async def create_patient(
    session: AsyncSession,
    oracle_patient_id: int,
    numero_dossier: str,
    nom: str,
    prenom: str,
    telephone: str,
    **kwargs
) -> Patient:
    """Crée un patient s'il n'existe pas déjà"""
    # Vérifier si le patient existe déjà
    stmt = select(Patient).where(Patient.numero_dossier == numero_dossier)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    
    if existing:
        logger.info(f"⏭️  Patient {numero_dossier} ({prenom} {nom}) existe déjà, ignoré")
        return existing
    
    # Convertir le numéro de téléphone au format international si nécessaire
    if telephone.startswith("0"):
        # Format belge : 0471034785 -> +32471034785
        telephone = "+32" + telephone[1:]
    
    # Données par défaut
    patient_data = {
        "oracle_patient_id": oracle_patient_id,
        "numero_dossier": numero_dossier,
        "nom": nom,
        "prenom": prenom,
        "telephone": telephone,
        "status": "actif",
        "consent_given": False,
        "risk_score": 0,
        **kwargs
    }
    
    patient = Patient(**patient_data)
    session.add(patient)
    await session.flush()
    logger.info(f"✅ Patient créé : {prenom} {nom} ({numero_dossier}) - {telephone}")
    return patient


async def main():
    """Fonction principale"""
    logger.info("=" * 60)
    logger.info("👥 Création de patients dans la base de données")
    logger.info("=" * 60)
    logger.info("")
    
    async with AsyncSessionLocal() as session:
        try:
            patients_created = []
            
            # Patient 1: Oliver
            logger.info("1️⃣  Création du patient Oliver...")
            oliver = await create_patient(
                session,
                oracle_patient_id=-1000001,  # ID négatif pour patients créés manuellement
                numero_dossier="PAT-2024-OLIVER",
                nom="Dupont",
                prenom="Oliver",
                telephone="0471034785",
                email="oliver.dupont@example.com",
                date_naissance=datetime(1985, 6, 15),
                sexe="M",
                adresse="Avenue de la Liberté 42",
                ville="Bruxelles",
                code_postal="1000",
                service_hospitalisation="Cardiologie",
                date_admission=datetime.now() - timedelta(days=10),
                date_sortie=datetime.now() - timedelta(days=3),
                diagnostic_principal="Hypertension artérielle",
                medecin_responsable="Dr. Martin",
                status="actif",
                risk_score=4,
                consent_given=True,
                consent_date=datetime.now() - timedelta(days=2),
                notes="Patient suivi pour hypertension. Compliance médicamenteuse bonne."
            )
            patients_created.append(oliver)
            
            # Patient 2: Andreas
            logger.info("")
            logger.info("2️⃣  Création du patient Andreas...")
            andreas = await create_patient(
                session,
                oracle_patient_id=-1000002,
                numero_dossier="PAT-2024-ANDREAS",
                nom="Van Der Berg",
                prenom="Andreas",
                telephone="0472201535",
                email="andreas.vanderberg@example.com",
                date_naissance=datetime(1978, 11, 22),
                sexe="M",
                adresse="Rue de la Paix 78",
                ville="Anvers",
                code_postal="2000",
                service_hospitalisation="Pneumologie",
                date_admission=datetime.now() - timedelta(days=14),
                date_sortie=datetime.now() - timedelta(days=6),
                diagnostic_principal="Asthme sévère",
                medecin_responsable="Dr. Vermeulen",
                status="prioritaire",
                risk_score=6,
                consent_given=True,
                consent_date=datetime.now() - timedelta(days=5),
                notes="Patient asthmatique nécessitant un suivi régulier. Vérifier la compliance aux inhalateurs."
            )
            patients_created.append(andreas)
            
            # Patient 3: Sophie (patient supplémentaire)
            logger.info("")
            logger.info("3️⃣  Création du patient Sophie...")
            sophie = await create_patient(
                session,
                oracle_patient_id=-1000003,
                numero_dossier="PAT-2024-SOPHIE",
                nom="Lemaire",
                prenom="Sophie",
                telephone="0475123456",
                email="sophie.lemaire@example.com",
                date_naissance=datetime(1992, 3, 8),
                sexe="F",
                adresse="Boulevard du Roi 156",
                ville="Gand",
                code_postal="9000",
                service_hospitalisation="Médecine interne",
                date_admission=datetime.now() - timedelta(days=7),
                date_sortie=datetime.now() - timedelta(days=2),
                diagnostic_principal="Diabète de type 1",
                medecin_responsable="Dr. Peeters",
                status="actif",
                risk_score=5,
                consent_given=True,
                consent_date=datetime.now() - timedelta(days=1),
                notes="Jeune patiente diabétique. Suivi de la glycémie important."
            )
            patients_created.append(sophie)
            
            # Patient 4: Jean (patient supplémentaire)
            logger.info("")
            logger.info("4️⃣  Création du patient Jean...")
            jean = await create_patient(
                session,
                oracle_patient_id=-1000004,
                numero_dossier="PAT-2024-JEAN",
                nom="Moreau",
                prenom="Jean",
                telephone="0476234567",
                email="jean.moreau@example.com",
                date_naissance=datetime(1955, 9, 30),
                sexe="M",
                adresse="Place du Marché 23",
                ville="Liège",
                code_postal="4000",
                service_hospitalisation="Gériatrie",
                date_admission=datetime.now() - timedelta(days=18),
                date_sortie=datetime.now() - timedelta(days=8),
                diagnostic_principal="Fracture du col du fémur",
                medecin_responsable="Dr. De Vries",
                status="prioritaire",
                risk_score=7,
                consent_given=True,
                consent_date=datetime.now() - timedelta(days=7),
                notes="Patient âgé, suivi de la rééducation post-fracture. Risque de chute."
            )
            patients_created.append(jean)
            
            # Patient 5: Emma (patient supplémentaire)
            logger.info("")
            logger.info("5️⃣  Création du patient Emma...")
            emma = await create_patient(
                session,
                oracle_patient_id=-1000005,
                numero_dossier="PAT-2024-EMMA",
                nom="Jacobs",
                prenom="Emma",
                telephone="0477345678",
                email="emma.jacobs@example.com",
                date_naissance=datetime(1988, 12, 5),
                sexe="F",
                adresse="Chaussée de Charleroi 89",
                ville="Bruxelles",
                code_postal="1060",
                service_hospitalisation="Chirurgie",
                date_admission=datetime.now() - timedelta(days=5),
                date_sortie=datetime.now() - timedelta(days=1),
                diagnostic_principal="Appendicite opérée",
                medecin_responsable="Dr. Janssen",
                status="actif",
                risk_score=2,
                consent_given=True,
                consent_date=datetime.now() - timedelta(hours=12),
                notes="Récupération post-opératoire normale. Pas de complications."
            )
            patients_created.append(emma)
            
            # Patient 6: Marc (patient supplémentaire)
            logger.info("")
            logger.info("6️⃣  Création du patient Marc...")
            marc = await create_patient(
                session,
                oracle_patient_id=-1000006,
                numero_dossier="PAT-2024-MARC",
                nom="Wouters",
                prenom="Marc",
                telephone="0478456789",
                email="marc.wouters@example.com",
                date_naissance=datetime(1970, 4, 18),
                sexe="M",
                adresse="Rue de Namur 134",
                ville="Mons",
                code_postal="7000",
                service_hospitalisation="Oncologie",
                date_admission=datetime.now() - timedelta(days=22),
                date_sortie=datetime.now() - timedelta(days=15),
                diagnostic_principal="Suivi post-chimiothérapie",
                medecin_responsable="Dr. Van Der Berg",
                status="prioritaire",
                risk_score=6,
                consent_given=True,
                consent_date=datetime.now() - timedelta(days=14),
                notes="Surveillance des effets secondaires de la chimiothérapie. Suivi régulier nécessaire."
            )
            patients_created.append(marc)
            
            # Patient 7: Manon Picca
            logger.info("")
            logger.info("7️⃣  Création du patient Manon...")
            manon = await create_patient(
                session,
                oracle_patient_id=-1000007,
                numero_dossier="PAT-2024-MANON",
                nom="Picca",
                prenom="Manon",
                telephone="0499898599",
                status="actif",
                risk_score=0,
                consent_given=False,
            )
            patients_created.append(manon)
            
            # Patient 8: Delphine Horlon
            logger.info("")
            logger.info("8️⃣  Création de la patiente Delphine...")
            delphine = await create_patient(
                session,
                oracle_patient_id=-1000008,
                numero_dossier="PAT-2024-DELPHINE",
                nom="Horlon",
                prenom="Delphine",
                telephone="0479612837",
                email="delphine.horlon@example.com",
                date_naissance=datetime(1978, 5, 9),
                sexe="F",
                adresse="Rue des Lilas 17",
                ville="Namur",
                code_postal="5000",
                service_hospitalisation="Neurologie",
                date_admission=datetime.now() - timedelta(days=9),
                date_sortie=datetime.now() - timedelta(days=2),
                diagnostic_principal="Migraine chronique avec aura",
                medecin_responsable="Dr. Lecomte",
                status="actif",
                risk_score=3,
                consent_given=True,
                consent_date=datetime.now() - timedelta(days=1),
                notes="Patiente suivie pour migraines chroniques. Traitement de fond instauré. Bonne tolérance."
            )
            patients_created.append(delphine)

            # Commit final
            await session.commit()
            
            logger.info("")
            logger.info("=" * 60)
            logger.info("✅ Patients créés avec succès !")
            logger.info("=" * 60)
            logger.info("")
            logger.info(f"📊 Résumé: {len(patients_created)} patients créés")
            logger.info("")
            logger.info("Patients créés:")
            for patient in patients_created:
                logger.info(f"   • {patient.prenom} {patient.nom} ({patient.numero_dossier}) - {patient.telephone}")
            logger.info("")
            
        except Exception as e:
            await session.rollback()
            logger.error(f"❌ Erreur lors de la création des patients: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(main())

