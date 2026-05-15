"""
Modèle Transcription pour les transcriptions d'appels
"""
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.analysis import Analysis
    from app.models.call import Call


class Transcription(Base):
    """Modèle pour les transcriptions audio des appels"""
    
    __tablename__ = "transcriptions"
    
    # Colonnes
    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        nullable=False,
    )
    
    # Relation avec l'appel
    call_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("calls.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    
    # Contenu de la transcription
    full_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    
    # Langue et modèle
    language: Mapped[str] = mapped_column(
        String(10),
        default="fr-BE",
        nullable=False,
    )
    whisper_model: Mapped[str] = mapped_column(
        String(50),
        default="large-v3",
        nullable=False,
    )
    
    # Métriques de qualité
    confidence: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        comment="Score de confiance global (0.0 à 1.0)",
    )
    
    # Segments avec timestamps
    segments: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        comment="Segments de texte avec timestamps et metadata",
    )
    
    # Performance
    processing_time: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        comment="Temps de traitement en secondes",
    )
    
    # Métadonnées
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    # Relations ORM
    call: Mapped["Call"] = relationship(
        "Call",
        back_populates="transcription",
    )
    analysis: Mapped[Optional["Analysis"]] = relationship(
        "Analysis",
        back_populates="transcription",
        uselist=False,
        cascade="all, delete-orphan",
    )
    
    def __repr__(self) -> str:
        return f"<Transcription {self.id} - Call: {self.call_id}>"
    
    def __str__(self) -> str:
        return f"Transcription de l'appel {self.call_id}"
    
    @property
    def word_count(self) -> int:
        """Retourne le nombre de mots dans la transcription"""
        return len(self.full_text.split()) if self.full_text else 0
    
    @property
    def char_count(self) -> int:
        """Retourne le nombre de caractères"""
        return len(self.full_text) if self.full_text else 0
    
    @property
    def segment_count(self) -> int:
        """Retourne le nombre de segments"""
        if not self.segments:
            return 0
        if isinstance(self.segments, list):
            return len(self.segments)
        if isinstance(self.segments, dict):
            return len(self.segments.get("segments", []))
        return 0
    
    @property
    def has_high_confidence(self) -> bool:
        """Vérifie si la transcription a une haute confiance"""
        return self.confidence is not None and self.confidence >= 0.8
    
    @property
    def summary(self) -> str:
        """Retourne un résumé de la transcription"""
        if not self.full_text:
            return ""
        words = self.full_text.split()
        if len(words) <= 50:
            return self.full_text
        return " ".join(words[:50]) + "..."
    
    def get_segment_at_time(self, timestamp: float) -> Optional[Dict[str, Any]]:
        """
        Retourne le segment à un timestamp donné
        
        Args:
            timestamp: Temps en secondes
            
        Returns:
            Segment correspondant ou None
        """
        if not self.segments or not isinstance(self.segments, dict):
            return None
        
        segments = self.segments.get("segments", [])
        for segment in segments:
            start = segment.get("start", 0)
            end = segment.get("end", 0)
            if start <= timestamp <= end:
                return segment
        
        return None

