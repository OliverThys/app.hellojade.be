#!/usr/bin/env python3
"""
Script pour générer des données mockées cohérentes pour HelloJADE

Ce script crée :
- Des patients avec des profils variés (actif, prioritaire, urgence)
- Des appels téléphoniques avec transcriptions
- Des analyses IA avec scores de risque, alertes et recommandations

Usage:
    python scripts/seed_mock_data.py [--clear] [--count COUNT]
"""
import asyncio
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List
from uuid import UUID, uuid4

# Ajouter le répertoire parent au path pour les imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import get_password_hash
from app.database import AsyncSessionLocal
from app.models.analysis import Analysis
from app.models.call import Call
from app.models.patient import Patient
from app.models.transcription import Transcription
from app.models.user import User

logger = get_logger(__name__)

# Données mockées - Patients
MOCK_PATIENTS = [
    {
        "oracle_patient_id": 1001,
        "numero_dossier": "PAT-2024-001",
        "nom": "Dubois",
        "prenom": "Marie",
        "telephone": "+32471234567",
        "email": "marie.dubois@example.com",
        "date_naissance": datetime(1958, 3, 15),
        "sexe": "F",
        "adresse": "Rue de la Santé 45",
        "ville": "Bruxelles",
        "code_postal": "1000",
        "service_hospitalisation": "Cardiologie",
        "date_admission": datetime.now() - timedelta(days=12),
        "date_sortie": datetime.now() - timedelta(days=5),
        "diagnostic_principal": "Infarctus du myocarde",
        "medecin_responsable": "Dr. Martin",
        "status": "prioritaire",
        "risk_score": 8,
        "consent_given": True,
        "consent_date": datetime.now() - timedelta(days=4),
        "notes": "Patient à suivre de près après sortie d'hospitalisation.",
    },
    {
        "oracle_patient_id": 1002,
        "numero_dossier": "PAT-2024-002",
        "nom": "Martin",
        "prenom": "Pierre",
        "telephone": "+32471234568",
        "email": "pierre.martin@example.com",
        "date_naissance": datetime(1972, 7, 22),
        "sexe": "M",
        "adresse": "Avenue des Fleurs 123",
        "ville": "Anvers",
        "code_postal": "2000",
        "service_hospitalisation": "Chirurgie",
        "date_admission": datetime.now() - timedelta(days=8),
        "date_sortie": datetime.now() - timedelta(days=2),
        "diagnostic_principal": "Appendicite aiguë opérée",
        "medecin_responsable": "Dr. Janssen",
        "status": "actif",
        "risk_score": 3,
        "consent_given": True,
        "consent_date": datetime.now() - timedelta(days=1),
        "notes": "Récupération normale, pas de complications.",
    },
    {
        "oracle_patient_id": 1003,
        "numero_dossier": "PAT-2024-003",
        "nom": "Lefebvre",
        "prenom": "Sophie",
        "telephone": "+32471234569",
        "email": "sophie.lefebvre@example.com",
        "date_naissance": datetime(1985, 11, 8),
        "sexe": "F",
        "adresse": "Boulevard de la République 78",
        "ville": "Gand",
        "code_postal": "9000",
        "service_hospitalisation": "Pneumologie",
        "date_admission": datetime.now() - timedelta(days=15),
        "date_sortie": datetime.now() - timedelta(days=7),
        "diagnostic_principal": "Pneumonie sévère",
        "medecin_responsable": "Dr. Vermeulen",
        "status": "urgence",
        "risk_score": 9,
        "consent_given": True,
        "consent_date": datetime.now() - timedelta(days=6),
        "notes": "Patient avec difficultés respiratoires persistantes. Suivi intensif requis.",
    },
    {
        "oracle_patient_id": 1004,
        "numero_dossier": "PAT-2024-004",
        "nom": "Willems",
        "prenom": "Jean",
        "telephone": "+32471234570",
        "email": "jean.willems@example.com",
        "date_naissance": datetime(1945, 2, 14),
        "sexe": "M",
        "adresse": "Place du Marché 22",
        "ville": "Liège",
        "code_postal": "4000",
        "service_hospitalisation": "Gériatrie",
        "date_admission": datetime.now() - timedelta(days=20),
        "date_sortie": datetime.now() - timedelta(days=10),
        "diagnostic_principal": "Chute avec fracture du col du fémur",
        "medecin_responsable": "Dr. De Vries",
        "status": "prioritaire",
        "risk_score": 7,
        "consent_given": True,
        "consent_date": datetime.now() - timedelta(days=9),
        "notes": "Patient âgé, suivi de la rééducation importante.",
    },
    {
        "oracle_patient_id": 1005,
        "numero_dossier": "PAT-2024-005",
        "nom": "De Smet",
        "prenom": "Elise",
        "telephone": "+32471234571",
        "email": "elise.desmet@example.com",
        "date_naissance": datetime(1990, 5, 30),
        "sexe": "F",
        "adresse": "Chaussée de Charleroi 156",
        "ville": "Bruxelles",
        "code_postal": "1060",
        "service_hospitalisation": "Médecine interne",
        "date_admission": datetime.now() - timedelta(days=6),
        "date_sortie": datetime.now() - timedelta(days=1),
        "diagnostic_principal": "Diabète de type 2 mal équilibré",
        "medecin_responsable": "Dr. Peeters",
        "status": "actif",
        "risk_score": 5,
        "consent_given": True,
        "consent_date": datetime.now() - timedelta(hours=12),
        "notes": "Bilan glycémique à surveiller.",
    },
    {
        "oracle_patient_id": 1006,
        "numero_dossier": "PAT-2024-006",
        "nom": "Vandenberghe",
        "prenom": "Luc",
        "telephone": "+32471234572",
        "email": "luc.vandenberghe@example.com",
        "date_naissance": datetime(1965, 9, 12),
        "sexe": "M",
        "adresse": "Rue de Namur 89",
        "ville": "Mons",
        "code_postal": "7000",
        "service_hospitalisation": "Oncologie",
        "date_admission": datetime.now() - timedelta(days=25),
        "date_sortie": datetime.now() - timedelta(days=18),
        "diagnostic_principal": "Chimiothérapie - suivi post-traitement",
        "medecin_responsable": "Dr. Van Der Berg",
        "status": "prioritaire",
        "risk_score": 6,
        "consent_given": True,
        "consent_date": datetime.now() - timedelta(days=17),
        "notes": "Suivi des effets secondaires de la chimiothérapie.",
    },
]

# Transcriptions mockées réalistes
MOCK_TRANSCRIPTIONS = [
    """Bonjour, c'est Marie Dubois au téléphone. Oui, je me sens mieux qu'à la sortie de l'hôpital, mais j'ai encore quelques douleurs dans la poitrine de temps en temps, surtout quand je monte les escaliers. Mon niveau de douleur serait environ 4 sur 10. Non, je n'ai pas de fièvre, ma température est normale. Oui, je prends bien mes médicaments tous les jours comme prescrit. Mon moral va mieux, je dirais 4 sur 5. J'ai encore un peu peur mais ça s'améliore. Oui, j'ai bien reçu toutes les informations sur mon traitement.""",
    """Bonjour, ici Pierre Martin. Tout va bien pour moi ! Les douleurs de l'opération ont presque disparu, peut-être 1 sur 10 quand je bouge trop. Pas de fièvre, température normale. Je prends mes antibiotiques régulièrement comme prévu. Je me sens très bien, moral à 5 sur 5. La cicatrisation se passe bien, je suis content de mon rétablissement.""",
    """Allô ? Oui, c'est Sophie Lefebvre. Euh... je tousse encore beaucoup et j'ai du mal à respirer profondément. Ma douleur dans la poitrine est à 6 sur 10. J'ai eu un peu de fièvre hier soir, 38 degrés. Ça fait 3 jours maintenant. Pour les médicaments, je les prends mais j'ai parfois oublié, peut-être une fois sur deux. Mon moral n'est pas terrible, je dirais 2 sur 5. Je m'inquiète pour ma santé.""",
    """Bonjour, Jean Willems à l'appareil. J'ai encore mal à la hanche, ça fait 7 sur 10. Pas de fièvre par contre. Oui, je prends mes médicaments contre la douleur, mais pas toujours aux bons horaires. Mon moral est correct, 3 sur 5. La rééducation est difficile mais je progresse.""",
    """Salut, c'est Elise De Smet. Je me sens mieux depuis la sortie. Pas vraiment de douleur, peut-être 2 sur 10. Pas de fièvre. Pour mes médicaments contre le diabète, je les prends régulièrement. Mon moral est bon, 4 sur 5. J'ai suivi les conseils nutritionnels qu'on m'a donnés.""",
    """Bonjour, Luc Vandenberghe au téléphone. J'ai des nausées de temps en temps, douleur à 3 sur 10. Pas de fièvre. Je prends mes médicaments mais c'est difficile à cause des nausées. Mon moral fluctue, aujourd'hui 3 sur 5. Les effets secondaires de la chimiothérapie se font encore sentir.""",
]

# Analyses IA mockées avec différents profils de risque
MOCK_ANALYSES = [
    {
        "pain_level": 4,
        "pain_location": "Poitrine, côté gauche",
        "pain_description": "Douleurs occasionnelles lors d'efforts",
        "has_fever": False,
        "fever_temperature": None,
        "takes_medication": True,
        "medication_regularity": "toujours",
        "moral_state": 4,
        "moral_description": "Amélioration progressive, quelques appréhensions persistantes",
        "summary": "Patient en bonne récupération post-infarctus. Douleurs résiduelles légères, compliance médicamenteuse excellente. Moral en amélioration mais nécessite encore du soutien psychologique.",
        "alerts": [
            {
                "type": "douleur",
                "severity": "warning",
                "message": "Douleurs thoraciques persistantes lors d'efforts",
                "action": "Surveiller l'évolution et consulter si aggravation"
            }
        ],
        "recommendations": [
            "Continuer la prise régulière des médicaments",
            "Reprendre l'activité physique progressivement",
            "Consulter en cas d'aggravation des douleurs thoraciques",
            "Suivi psychologique recommandé"
        ],
        "risk_score": 4,
    },
    {
        "pain_level": 1,
        "pain_location": "Cicatrice abdominale",
        "pain_description": "Douleur minime lors des mouvements",
        "has_fever": False,
        "fever_temperature": None,
        "takes_medication": True,
        "medication_regularity": "toujours",
        "moral_state": 5,
        "moral_description": "Excellent moral, patient très satisfait de sa récupération",
        "summary": "Récupération excellente post-appendicectomie. Aucun signe d'infection, cicatrisation normale. Compliance parfaite aux traitements.",
        "alerts": [],
        "recommendations": [
            "Continuer la prise des antibiotiques jusqu'à la fin",
            "Reprendre progressivement les activités normales",
            "Surveiller la cicatrisation"
        ],
        "risk_score": 1,
    },
    {
        "pain_level": 6,
        "pain_location": "Poitrine, difficultés respiratoires",
        "pain_description": "Toux persistante et essoufflement",
        "has_fever": True,
        "fever_temperature": 38.0,
        "fever_duration": "3 jours",
        "takes_medication": True,
        "medication_regularity": "parfois",
        "medication_issues": "Oublis fréquents des prises médicamenteuses",
        "moral_state": 2,
        "moral_description": "Moral bas, anxiété importante concernant l'évolution",
        "summary": "⚠️ SITUATION PRÉOCCUPANTE : Fièvre persistante avec symptômes respiratoires non résolus. Compliance médicamenteuse insuffisante. Risque de récidive ou de complications. Attention médicale requise.",
        "alerts": [
            {
                "type": "fièvre",
                "severity": "urgent",
                "message": "Fièvre persistante à 38°C depuis 3 jours",
                "action": "Consulter rapidement un médecin ou se rendre aux urgences"
            },
            {
                "type": "respiration",
                "severity": "urgent",
                "message": "Difficultés respiratoires persistantes",
                "action": "Évaluation médicale immédiate nécessaire"
            },
            {
                "type": "medication",
                "severity": "warning",
                "message": "Compliance médicamenteuse insuffisante",
                "action": "Rappeler l'importance de la prise régulière des médicaments"
            }
        ],
        "recommendations": [
            "⚠️ CONSULTATION MÉDICALE URGENTE requise",
            "Améliorer la compliance médicamenteuse (aide-mémoire, pilulier)",
            "Surveillance de la température toutes les 4 heures",
            "Repos strict jusqu'à consultation",
            "Support psychologique pour l'anxiété"
        ],
        "risk_score": 9,
    },
    {
        "pain_level": 7,
        "pain_location": "Hanche droite",
        "pain_description": "Douleurs importantes lors de la marche et des mouvements",
        "has_fever": False,
        "fever_temperature": None,
        "takes_medication": True,
        "medication_regularity": "souvent",
        "medication_issues": "Prise parfois aux mauvais horaires",
        "moral_state": 3,
        "moral_description": "Moral modéré, découragement face à la lenteur de la rééducation",
        "summary": "Récupération post-fracture en cours. Douleurs importantes nécessitant un ajustement de l'antalgie. Compliance partielle aux traitements. Rééducation progressive mais difficile.",
        "alerts": [
            {
                "type": "douleur",
                "severity": "warning",
                "message": "Douleurs importantes persistantes (7/10)",
                "action": "Évaluer l'efficacité de l'antalgie et ajuster si nécessaire"
            }
        ],
        "recommendations": [
            "Optimiser la prise des antalgiques (horaires réguliers)",
            "Continuer la rééducation avec un kinésithérapeute",
            "Surveiller la mobilité et la douleur",
            "Support psychologique pour maintenir la motivation"
        ],
        "risk_score": 6,
    },
    {
        "pain_level": 2,
        "pain_location": "Aucune douleur significative",
        "pain_description": "Généralement bien",
        "has_fever": False,
        "fever_temperature": None,
        "takes_medication": True,
        "medication_regularity": "toujours",
        "moral_state": 4,
        "moral_description": "Bon moral, patient engagé dans son traitement",
        "summary": "Patient diabétique avec bonne compliance au traitement. Glycémie en cours de stabilisation. Application des recommandations nutritionnelles. Évolution favorable.",
        "alerts": [],
        "recommendations": [
            "Continuer le suivi glycémique régulier",
            "Maintenir le régime alimentaire prescrit",
            "Activité physique modérée recommandée"
        ],
        "risk_score": 3,
    },
    {
        "pain_level": 3,
        "pain_location": "Estomac, nausées",
        "pain_description": "Nausées intermittentes",
        "has_fever": False,
        "fever_temperature": None,
        "takes_medication": True,
        "medication_regularity": "souvent",
        "medication_issues": "Difficultés à prendre les médicaments à cause des nausées",
        "moral_state": 3,
        "moral_description": "Moral fluctuant, effets secondaires de la chimiothérapie difficiles à gérer",
        "summary": "Suivi post-chimiothérapie. Effets secondaires persistants (nausées) affectant la compliance médicamenteuse. Moral instable nécessitant un soutien.",
        "alerts": [
            {
                "type": "medication",
                "severity": "warning",
                "message": "Difficultés à prendre les médicaments à cause des nausées",
                "action": "Consulter l'équipe médicale pour ajuster la prise médicamenteuse"
            }
        ],
        "recommendations": [
            "Consulter pour anti-nauséeux si nécessaire",
            "Adapter les horaires de prise des médicaments",
            "Surveillance des effets secondaires",
            "Support psychologique pour gérer le moral"
        ],
        "risk_score": 5,
    },
]


async def get_or_create_user(session: AsyncSession, full_name: str, email: str, username: str, role: str = "medecin") -> User:
    """Récupère ou crée un utilisateur"""
    stmt = select(User).where(User.email == email)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    
    if user:
        return user
    
    user = User(
        email=email,
        username=username,
        hashed_password=get_password_hash("demo123"),  # Mot de passe par défaut
        full_name=full_name,
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def create_mock_patients(session: AsyncSession, count: int = None) -> List[Patient]:
    """Crée des patients mockés"""
    patients = []
    patient_data = MOCK_PATIENTS[:count] if count else MOCK_PATIENTS
    
    for data in patient_data:
        # Vérifier si le patient existe déjà
        stmt = select(Patient).where(Patient.numero_dossier == data["numero_dossier"])
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if existing:
            logger.info(f"⏭️  Patient {data['numero_dossier']} existe déjà, ignoré")
            patients.append(existing)
            continue
        
        patient = Patient(**data)
        session.add(patient)
        patients.append(patient)
    
    await session.flush()
    logger.info(f"✅ {len(patients)} patients créés/mis à jour")
    return patients


async def create_mock_calls(
    session: AsyncSession,
    patients: List[Patient],
    users: List[User],
    count: int = None
) -> List[Call]:
    """Crée des appels mockés avec historique pour chaque patient"""
    calls = []
    
    # Créer plusieurs appels pour chaque patient pour avoir un historique
    patient_list = patients[:count] if count else patients
    
    for i, patient in enumerate(patient_list):
        # Créer 2-4 appels par patient pour avoir un historique
        num_calls = random.randint(2, 4)
        
        # Le premier appel (le plus récent) sera celui avec transcription et analyse
        # Les autres seront l'historique
        for call_idx in range(num_calls):
            # Dates variées : le plus récent dans les 2 derniers jours, les autres jusqu'à 30 jours
            if call_idx == 0:
                # Appel récent (pour transcription/analyse)
                days_ago = random.randint(0, 2)
            else:
                # Appels historiques
                days_ago = random.randint(3, 30)
            
            start_time = datetime.now() - timedelta(days=days_ago, hours=random.randint(9, 17))
            
            # Durée de l'appel (2-15 minutes)
            duration_seconds = random.randint(120, 900)
            answer_time = start_time + timedelta(seconds=random.randint(5, 30))
            end_time = answer_time + timedelta(seconds=duration_seconds)
            
            # Statut de l'appel : varié selon l'index
            if call_idx == 0:
                # Le plus récent est généralement completed
                status = "completed" if random.random() > 0.15 else random.choice(["failed", "no_answer", "busy"])
            else:
                # Les anciens appels ont des statuts variés
                status = random.choices(
                    ["completed", "completed", "completed", "no_answer", "failed", "busy", "cancelled"],
                    weights=[60, 60, 60, 10, 8, 5, 2]
                )[0]
            
            # Notes pour certains appels
            notes = None
            if status == "failed":
                notes = random.choice([
                    "Ligne occupée",
                    "Pas de réponse après plusieurs tentatives",
                    "Numéro incorrect",
                    None
                ])
            elif status == "completed" and call_idx > 0:
                notes = random.choice([
                    "Appel de suivi routinier",
                    "Patient disponible et réceptif",
                    "Bilan post-hospitalisation",
                    None
                ])
            
            call = Call(
                patient_id=patient.id,
                initiated_by=random.choice(users).id if users else None,
                caller_number="+32470123456",
                callee_number=patient.telephone or "+32471234567",
                status=status,
                start_time=start_time,
                answer_time=answer_time if status == "completed" else None,
                end_time=end_time if status == "completed" else None,
                duration=duration_seconds if status == "completed" else None,
                recording_path=f"recordings/call_{patient.numero_dossier}_{start_time.strftime('%Y%m%d_%H%M%S')}.wav" if status == "completed" else None,
                recording_size=random.randint(500000, 5000000) if status == "completed" else None,
                failure_reason=notes if status in ["failed", "no_answer", "busy"] else None,
                notes=notes if status == "completed" else None,
            )
            
            session.add(call)
            calls.append(call)
            
            # Mettre à jour le last_call_at du patient avec le plus récent
            if status == "completed" and (patient.last_call_at is None or start_time > patient.last_call_at):
                patient.last_call_at = start_time
    
    await session.flush()
    logger.info(f"✅ {len(calls)} appels créés")
    return calls


async def create_mock_transcriptions(
    session: AsyncSession,
    calls: List[Call],
    count: int = None
) -> List[Transcription]:
    """Crée des transcriptions mockées pour les appels récents et complétés"""
    transcriptions = []
    
    # Trier les appels par date (plus récent en premier) et prendre seulement les completed
    call_list = sorted(
        [c for c in calls if c.status == "completed"],
        key=lambda x: x.start_time or x.created_at,
        reverse=True
    )
    
    # Créer des transcriptions pour les appels les plus récents (1 par patient maximum)
    # Grouper par patient pour avoir au plus une transcription par patient
    patients_seen = set()
    transcriptions_to_create = []
    
    for call in call_list:
        if call.patient_id not in patients_seen:
            transcriptions_to_create.append(call)
            patients_seen.add(call.patient_id)
    
    # Limiter si count est spécifié
    transcriptions_to_create = transcriptions_to_create[:count] if count else transcriptions_to_create
    
    for i, call in enumerate(transcriptions_to_create):
        transcription_text = MOCK_TRANSCRIPTIONS[i % len(MOCK_TRANSCRIPTIONS)]
        
        transcription = Transcription(
            call_id=call.id,
            full_text=transcription_text,
            language="fr-BE",
            whisper_model="large-v3",
            confidence=random.uniform(0.85, 0.98),
            segments={
                "segments": [
                    {
                        "start": j * 10.0,
                        "end": (j + 1) * 10.0,
                        "text": transcription_text[max(0, j*50):min(len(transcription_text), (j+1)*50)],
                        "confidence": random.uniform(0.8, 0.95)
                    }
                    for j in range(len(transcription_text) // 50)
                ]
            },
            processing_time=random.uniform(2.5, 8.0),
        )
        
        session.add(transcription)
        transcriptions.append(transcription)
    
    await session.flush()
    logger.info(f"✅ {len(transcriptions)} transcriptions créées")
    return transcriptions


async def create_mock_analyses(
    session: AsyncSession,
    calls: List[Call],
    transcriptions: List[Transcription],
    count: int = None
) -> List[Analysis]:
    """Crée des analyses mockées"""
    analyses = []
    
    # Créer une analyse pour chaque transcription
    transcription_map = {t.call_id: t for t in transcriptions}
    call_list = [c for c in calls if c.status == "completed" and c.id in transcription_map]
    call_list = call_list[:count] if count else call_list
    
    for i, call in enumerate(call_list):
        analysis_data = MOCK_ANALYSES[i % len(MOCK_ANALYSES)].copy()
        transcription = transcription_map.get(call.id)
        
        analysis = Analysis(
            call_id=call.id,
            transcription_id=transcription.id if transcription else None,
            **analysis_data,
            model_used="llama3.1:8b",
            processing_time=random.uniform(1.5, 4.0),
            confidence=random.uniform(0.85, 0.95),
        )
        
        session.add(analysis)
        analyses.append(analysis)
        
        # Mettre à jour le risk_score du patient
        call.patient.risk_score = analysis_data["risk_score"]
    
    await session.flush()
    logger.info(f"✅ {len(analyses)} analyses créées")
    return analyses


async def clear_existing_data(session: AsyncSession):
    """Supprime toutes les données existantes (dangereux !)"""
    from sqlalchemy import text
    
    logger.warning("🗑️  Suppression des données existantes...")
    
    # Supprimer dans l'ordre des dépendances
    await session.execute(text("DELETE FROM analyses"))
    await session.execute(text("DELETE FROM transcriptions"))
    await session.execute(text("DELETE FROM calls"))
    await session.execute(text("DELETE FROM patients"))
    
    # Ne pas supprimer les users (garder l'admin)
    logger.info("✅ Données supprimées (users conservés)")
    await session.flush()


async def main(clear: bool = False, count: int = None):
    """Fonction principale"""
    logger.info("=" * 60)
    logger.info("📊 Génération de données mockées pour HelloJADE")
    logger.info("=" * 60)
    logger.info("")
    
    async with AsyncSessionLocal() as session:
        try:
            # 1. Nettoyer les données existantes si demandé
            if clear:
                await clear_existing_data(session)
            
            # 2. Créer/récupérer des utilisateurs
            logger.info("1️⃣  Création des utilisateurs...")
            users = [
                await get_or_create_user(
                    session,
                    "Dr. Martin",
                    "dr.martin@hellojadeapp.com",
                    "dr.martin",
                    "medecin"
                ),
                await get_or_create_user(
                    session,
                    "Infirmière Dupont",
                    "inf.dupont@hellojadeapp.com",
                    "inf.dupont",
                    "infirmier"
                ),
            ]
            
            # 3. Créer les patients
            logger.info("")
            logger.info("2️⃣  Création des patients...")
            patients = await create_mock_patients(session, count)
            
            # 4. Créer les appels
            logger.info("")
            logger.info("3️⃣  Création des appels...")
            calls = await create_mock_calls(session, patients, users, count)
            
            # 5. Créer les transcriptions
            logger.info("")
            logger.info("4️⃣  Création des transcriptions...")
            transcriptions = await create_mock_transcriptions(session, calls, count)
            
            # 6. Créer les analyses
            logger.info("")
            logger.info("5️⃣  Création des analyses IA...")
            analyses = await create_mock_analyses(session, calls, transcriptions, count)
            
            # Commit final
            await session.commit()
            
            logger.info("")
            logger.info("=" * 60)
            logger.info("✅ Données mockées générées avec succès !")
            logger.info("=" * 60)
            logger.info("")
            logger.info(f"📊 Résumé:")
            logger.info(f"   • {len(patients)} patients")
            logger.info(f"   • {len(calls)} appels")
            logger.info(f"   • {len(transcriptions)} transcriptions")
            logger.info(f"   • {len(analyses)} analyses IA")
            logger.info("")
            logger.info("💡 Vous pouvez maintenant prendre des screenshots !")
            
        except Exception as e:
            await session.rollback()
            logger.error(f"❌ Erreur lors de la génération des données: {e}")
            raise


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Générer des données mockées pour HelloJADE",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  # Générer toutes les données mockées
  python scripts/seed_mock_data.py
  
  # Générer seulement 3 patients
  python scripts/seed_mock_data.py --count 3
  
  # Réinitialiser et générer toutes les données
  python scripts/seed_mock_data.py --clear
        """
    )
    
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Supprimer les données existantes avant de créer les nouvelles",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Nombre de patients/appels à créer (défaut: tous)",
    )
    
    args = parser.parse_args()
    
    asyncio.run(main(clear=args.clear, count=args.count))

