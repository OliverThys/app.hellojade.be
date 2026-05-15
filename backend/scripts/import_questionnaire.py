"""
Script pour importer le questionnaire médical actuel dans la base de données.
"""
import asyncio
import sys
from pathlib import Path

# Ajouter le répertoire parent au PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.question import Question

# Questionnaire actuel
QUESTIONNAIRE_QUESTIONS = [
    {
        "question_id": "intro",
        "text": "Bonjour, je suis Hellojade, l'assistant vocal de l'hôpital.",
        "max_duration": 0,
        "order": -1,
        "question_type": "intro",
    },
    {
        "question_id": "douleur",
        "text": (
            "Avez-vous mal quelque part ? "
            "Si oui, sur une échelle de zéro à dix, où zéro signifie pas de douleur et dix une douleur insupportable, "
            "quel est votre score ? "
            "La douleur est-elle soulagée par les anti-douleur ?"
        ),
        "max_duration": 30,
        "order": 0,
    },
    {
        "question_id": "alimentation",
        "text": (
            "Mangez-vous normalement ? "
            "Si non, sur une échelle de zéro à dix, où zéro signifie aucune difficulté et dix impossible de manger, "
            "quel est votre score ? "
            "Savez-vous boire normalement ?"
        ),
        "max_duration": 25,
        "order": 1,
    },
    {
        "question_id": "nausees",
        "text": (
            "Avez-vous des nausées ou des vomissements ? "
            "Si oui, sur une échelle de zéro à dix, où zéro signifie très léger et dix très important, "
            "quel est votre score ? "
            "Avez-vous vu du sang dans les vomissements ?"
        ),
        "max_duration": 25,
        "order": 2,
    },
    {
        "question_id": "maux_de_tete",
        "text": (
            "Avez-vous eu des maux de tête ? "
            "Si oui, sur une échelle de zéro à dix, où zéro signifie léger et dix très fort, "
            "quel est votre score ?"
        ),
        "max_duration": 20,
        "order": 3,
    },
    {
        "question_id": "saignements",
        "text": (
            "Avez-vous eu des saignements ? "
            "Si oui, sur une échelle de zéro à dix, où zéro signifie très léger et dix très abondant, "
            "quel est votre score ? "
            "Les saignements sont-ils à présent arrêtés ? "
            "Observez-vous des signes d'infection comme un suintement ou une rougeur à l'endroit de votre plaie ?"
        ),
        "max_duration": 30,
        "order": 4,
    },
    {
        "question_id": "contact_medical",
        "text": (
            "Avez-vous contacté un médecin ou les urgences depuis l'opération ? "
            "Si oui, pour quelle raison ?"
        ),
        "max_duration": 25,
        "order": 5,
    },
    {
        "question_id": "consignes",
        "text": (
            "Avez-vous bien compris les consignes après l'opération ? "
            "Si non, précisez ce que vous n'avez pas compris."
        ),
        "max_duration": 25,
        "order": 6,
    },
    {
        "question_id": "outro",
        "text": "Merci pour vos réponses. Bon rétablissement. Au revoir.",
        "max_duration": 0,
        "order": 99,
        "question_type": "outro",
    },
]


async def import_questionnaire():
    """Importe le questionnaire dans la base de données."""
    async with AsyncSessionLocal() as db:
        print("🔄 Importation du questionnaire médical...")

        # Vérifier si des questions existent déjà
        result = await db.execute(select(Question))
        existing_questions = result.scalars().all()

        if existing_questions:
            print(f"⚠️  {len(existing_questions)} question(s) déjà présente(s) dans la base.")
            response = input("Voulez-vous les supprimer et réimporter ? (o/N) : ")
            if response.lower() == 'o':
                for q in existing_questions:
                    await db.delete(q)
                await db.commit()
                print("✅ Questions existantes supprimées.")
            else:
                print("❌ Import annulé.")
                return

        # Importer les questions
        questions_created = 0
        for q_data in QUESTIONNAIRE_QUESTIONS:
            question = Question(
                question_id=q_data["question_id"],
                text=q_data["text"],
                max_duration=q_data["max_duration"],
                order=q_data["order"],
                is_active=True,
                question_type=q_data.get("question_type", "question"),
            )
            db.add(question)
            questions_created += 1
            q_type = q_data.get("question_type", "question")
            print(f"  ✓ {q_type.upper()}: {q_data['question_id']}")

        await db.commit()
        print(f"\n✅ {questions_created} questions importées avec succès !")

        # Afficher le résumé
        print("\n📋 Résumé du questionnaire :")
        result = await db.execute(select(Question).order_by(Question.order))
        all_questions = result.scalars().all()

        for q in all_questions:
            status = "✅ Active" if q.is_active else "❌ Inactive"
            print(f"  {q.order + 1}. [{q.question_id}] {status} - {q.max_duration}s")
            print(f"     {q.text[:80]}...")


if __name__ == "__main__":
    asyncio.run(import_questionnaire())
