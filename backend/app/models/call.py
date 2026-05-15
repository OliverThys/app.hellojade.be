"""
Modèle Call pour les appels téléphoniques
"""
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.analysis import Analysis
    from app.models.patient import Patient
    from app.models.report import Report
    from app.models.transcription import Transcription
    from app.models.user import User


class Call(Base):
    """Modèle pour les appels téléphoniques aux patients"""
    
    __tablename__ = "calls"
    
    # Colonnes
    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        nullable=False,
    )
    
    # Relations
    patient_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    initiated_by: Mapped[Optional[UUID]] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    
    # Informations Asterisk
    asterisk_call_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        unique=True,
        nullable=True,
        index=True,
    )
    asterisk_channel: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
    )
    
    # Numéros de téléphone
    caller_number: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    callee_number: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    
    # Statut de l'appel
    status: Mapped[str] = mapped_column(
        Enum(
            "pending",
            "ringing",
            "in_progress",
            "completed",
            "failed",
            "no_answer",
            "busy",
            "cancelled",
            "interrupted",
            name="call_status",
            create_constraint=False,  # L'enum existe déjà en base via Alembic
        ),
        nullable=False,
        default="pending",
        index=True,
    )
    
    # Timestamps
    start_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    answer_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    end_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    # Durée et enregistrement
    duration: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Durée en secondes",
    )
    recording_path: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    recording_size: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Taille en octets",
    )
    
    # Raisons d'échec ou notes
    failure_reason: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Métadonnées JSON (réponses, alertes, événements ARI)
    # Note: on utilise call_metadata au lieu de metadata car metadata est réservé dans SQLAlchemy
    call_metadata: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        default=dict,
        name="metadata",  # Nom de la colonne en base de données
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
    
    # Relations ORM
    patient: Mapped["Patient"] = relationship(
        "Patient",
        back_populates="calls",
    )
    initiated_by_user: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="initiated_calls",
    )
    transcription: Mapped[Optional["Transcription"]] = relationship(
        "Transcription",
        back_populates="call",
        uselist=False,
        cascade="all, delete-orphan",
    )
    analysis: Mapped[Optional["Analysis"]] = relationship(
        "Analysis",
        back_populates="call",
        uselist=False,
        cascade="all, delete-orphan",
    )
    reports: Mapped[list["Report"]] = relationship(
        "Report",
        back_populates="call",
        cascade="all, delete-orphan",
    )
    
    def __repr__(self) -> str:
        return f"<Call {self.id} - {self.status} - Patient: {self.patient_id}>"
    
    def __str__(self) -> str:
        return f"Appel {self.status} du {self.start_time or self.created_at}"
    
    @property
    def duration_minutes(self) -> Optional[float]:
        """Retourne la durée en minutes"""
        return self.duration / 60 if self.duration else None
    
    @property
    def is_successful(self) -> bool:
        """Vérifie si l'appel a été réussi"""
        return self.status == "completed"
    
    @property
    def is_failed(self) -> bool:
        """Vérifie si l'appel a échoué"""
        return self.status in ["failed", "no_answer", "busy", "cancelled"]
    
    @property
    def has_transcription(self) -> bool:
        """Vérifie si l'appel a une transcription"""
        return self.transcription is not None
    
    @property
    def has_analysis(self) -> bool:
        """Vérifie si l'appel a été analysé"""
        return self.analysis is not None
    
    @property
    def has_recording(self) -> bool:
        """Vérifie si l'appel a un enregistrement"""
        return self.recording_path is not None
    
    @property
    def recording_size_mb(self) -> Optional[float]:
        """Retourne la taille de l'enregistrement en MB"""
        return self.recording_size / (1024 * 1024) if self.recording_size else None

