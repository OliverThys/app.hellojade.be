"""
Schémas Pydantic pour les questions du questionnaire médical.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class QuestionBase(BaseModel):
    """Schéma de base pour une question."""

    question_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Identifiant unique de la question (ex: 'douleur', 'alimentation')",
    )
    text: str = Field(
        ...,
        min_length=1,
        description="Texte complet de la question à poser au patient",
    )
    max_duration: int = Field(
        default=30,
        ge=0,
        le=120,
        description="Durée maximale d'enregistrement de la réponse (en secondes, 0 pour intro/outro)",
    )
    order: int = Field(
        default=0,
        ge=-1,
        description="Ordre d'affichage dans le questionnaire (-1 pour intro, 0+ pour questions)",
    )
    is_active: bool = Field(
        default=True,
        description="Si false, la question n'est pas posée dans les appels automatisés",
    )
    question_type: str = Field(
        default="question",
        pattern="^(intro|question|outro)$",
        description="Type de question: 'intro', 'question', 'outro'",
    )
    is_follow_up: bool = Field(
        default=False,
        description="Si true, cette question est une sous-question d'une question principale",
    )
    parent_question_id: Optional[UUID] = Field(
        default=None,
        description="ID de la question principale si c'est une sous-question",
    )
    additional_info: Optional[dict] = Field(
        default=None,
        description="Infos complémentaires: conditions de déclenchement et sous-questions",
    )


class QuestionCreate(QuestionBase):
    """Schéma pour créer une nouvelle question."""
    pass


class QuestionUpdate(BaseModel):
    """Schéma pour mettre à jour une question."""

    question_id: Optional[str] = Field(
        None,
        min_length=1,
        max_length=100,
        description="Identifiant unique de la question",
    )
    text: Optional[str] = Field(
        None,
        min_length=1,
        description="Texte de la question",
    )
    max_duration: Optional[int] = Field(
        None,
        ge=0,
        le=120,
        description="Durée maximale d'enregistrement (en secondes, 0 pour intro/outro)",
    )
    order: Optional[int] = Field(
        None,
        ge=-1,
        description="Ordre d'affichage (-1 pour intro, 0+ pour questions)",
    )
    is_active: Optional[bool] = Field(
        None,
        description="Question active ou non",
    )
    question_type: Optional[str] = Field(
        None,
        pattern="^(intro|question|outro)$",
        description="Type de question: 'intro', 'question', 'outro'",
    )
    is_follow_up: Optional[bool] = Field(
        None,
        description="Si true, cette question est une sous-question d'une question principale",
    )
    parent_question_id: Optional[UUID] = Field(
        None,
        description="ID de la question principale si c'est une sous-question",
    )
    additional_info: Optional[dict] = Field(
        None,
        description="Infos complémentaires",
    )


class QuestionResponse(QuestionBase):
    """Schéma de réponse pour une question."""

    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class QuestionListResponse(BaseModel):
    """Schéma de réponse pour une liste de questions."""

    items: list[QuestionResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
