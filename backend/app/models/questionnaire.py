"""
Modèles Questionnaire et QuestionnaireAssignment.

Un Questionnaire est un template nommé contenant les questions (JSONB)
et les messages (JSONB). Une QuestionnaireAssignment lie un questionnaire
à une unité de soins (care_unit_id NULL = questionnaire par défaut).
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Questionnaire(Base):
    __tablename__ = "questionnaires"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Liste de MainQuestionDTO sérialisés
    questions: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    # MessagesPayload sérialisé : welcome, outro_normal, outro_alert, outro_transfer_failed
    messages: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    is_factory_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    assignments: Mapped[List["QuestionnaireAssignment"]] = relationship(
        "QuestionnaireAssignment",
        back_populates="questionnaire",
        foreign_keys="QuestionnaireAssignment.questionnaire_id",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Questionnaire {self.name!r}>"


class QuestionnaireAssignment(Base):
    """
    Lie un questionnaire à un service (care_unit_id).
    care_unit_id IS NULL → questionnaire par défaut (fallback pour tout service inconnu).

    Contraintes en production (PostgreSQL) : migration 012 — index unique partiel par service
    et un seul enregistrement défaut (care_unit_id NULL). Non reproduit sur SQLite (tests).
    """
    __tablename__ = "questionnaire_assignments"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    care_unit_id: Mapped[Optional[UUID]] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("care_units.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    questionnaire_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("questionnaires.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Questionnaire utilisé quand caller_role == "proche".
    # NULL → fallback sur questionnaire_id (questionnaire patient).
    # ON DELETE SET NULL : si le questionnaire proche est supprimé, retombe sur le patient.
    proche_questionnaire_id: Mapped[Optional[UUID]] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("questionnaires.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    questionnaire: Mapped["Questionnaire"] = relationship(
        "Questionnaire",
        back_populates="assignments",
        foreign_keys=[questionnaire_id],
    )

    def __repr__(self) -> str:
        label = str(self.care_unit_id) if self.care_unit_id else "default"
        return f"<QuestionnaireAssignment {label} → {self.questionnaire_id}>"
