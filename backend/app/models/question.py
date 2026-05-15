"""
Modèle Question pour les questions du questionnaire médical avec infos complémentaires.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Question(Base):
    """
    Modèle pour les questions du questionnaire médical post-hospitalisation.
    
    Chaque question peut avoir des infos complémentaires (additional_info) qui définissent :
    - Les conditions de déclenchement de sous-questions automatiques
    - Les sous-questions à poser si les conditions sont remplies
    """
    
    __tablename__ = "questions"
    
    # Colonnes
    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        nullable=False,
    )
    
    # Identifiant unique de la question (ex: "douleur", "alimentation")
    question_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
        comment="Identifiant unique de la question (ex: 'douleur', 'alimentation')",
    )
    
    # Texte de la question
    text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Texte complet de la question à poser au patient",
    )
    
    # Durée maximale d'enregistrement (en secondes)
    max_duration: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30,
        server_default="30",
        comment="Durée maximale d'enregistrement de la réponse (en secondes)",
    )
    
    # Ordre d'affichage dans le questionnaire
    order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        index=True,
        comment="Ordre d'affichage dans le questionnaire (0 = première question)",
    )
    
    # Question active ou non
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="Si false, la question n'est pas posée dans les appels automatisés",
    )

    # Type de question
    question_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="question",
        server_default="question",
        index=True,
        comment="Type de question: 'intro', 'question', 'outro'",
    )

    # Indique si cette question est une sous-question
    is_follow_up: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        index=True,
        comment="Si true, cette question est une sous-question d'une question principale",
    )

    # ID de la question principale (si c'est une sous-question)
    parent_question_id: Mapped[Optional[UUID]] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="ID de la question principale si c'est une sous-question",
    )

    # Relation vers la question principale
    parent_question: Mapped[Optional["Question"]] = relationship(
        "Question",
        remote_side=[id],
        backref="follow_up_questions_list",
        foreign_keys=[parent_question_id],
    )

    # Infos complémentaires (JSON) pour les questions de suivi automatiques
    # Structure:
    # {
    #   "trigger_conditions": {
    #     "pain_level": {"operator": ">", "value": 7},
    #     "has_nausea": {"operator": "==", "value": true}
    #   },
    #   "follow_up_questions": [
    #     {
    #       "id": "douleur_localisation",
    #       "text": "Où exactement avez-vous mal ?",
    #       "max_duration": 20
    #     },
    #     {
    #       "id": "douleur_antalgiques",
    #       "text": "Les antalgiques prescrits vous soulagent-ils ?",
    #       "max_duration": 15
    #     }
    #   ]
    # }
    additional_info: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        default=dict,
        comment="Infos complémentaires: conditions de déclenchement et sous-questions automatiques",
    )
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    
    def __repr__(self) -> str:
        return f"<Question {self.question_id} - Order: {self.order}>"
    
    def __str__(self) -> str:
        return f"Question {self.question_id}: {self.text[:50]}..."
    
    @property
    def has_follow_up_questions(self) -> bool:
        """Vérifie si la question a des sous-questions configurées."""
        if not self.additional_info:
            return False
        follow_ups = self.additional_info.get("follow_up_questions", [])
        return len(follow_ups) > 0
    
    @property
    def trigger_conditions(self) -> dict:
        """Retourne les conditions de déclenchement des sous-questions."""
        if not self.additional_info:
            return {}
        return self.additional_info.get("trigger_conditions", {})
    
    @property
    def follow_up_questions(self) -> list:
        """Retourne la liste des sous-questions à poser."""
        if not self.additional_info:
            return []
        return self.additional_info.get("follow_up_questions", [])

