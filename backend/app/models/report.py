"""
Modèle Report pour les rapports PDF générés
"""
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.analysis import Analysis
    from app.models.call import Call
    from app.models.user import User


class Report(Base):
    """Modèle pour les rapports PDF générés"""
    
    __tablename__ = "reports"
    
    # Colonnes
    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        nullable=False,
    )
    
    # Relations
    call_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("calls.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    analysis_id: Mapped[Optional[UUID]] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("analyses.id", ondelete="SET NULL"),
        nullable=True,
    )
    generated_by: Mapped[Optional[UUID]] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    # Détails du rapport
    report_type: Mapped[str] = mapped_column(
        String(50),
        default="standard",
        nullable=False,
        comment="Type de rapport (standard, detailed, summary)",
    )
    file_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Chemin vers le fichier PDF",
    )
    file_size: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Taille du fichier en octets",
    )
    file_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="Hash SHA256 du fichier",
    )
    
    # Statut
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        nullable=False,
        comment="Status (pending, generated, sent, error)",
    )
    
    # Email
    sent_to: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="Adresses email de destination",
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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
        back_populates="reports",
    )
    analysis: Mapped[Optional["Analysis"]] = relationship(
        "Analysis",
        back_populates="reports",
    )
    generated_by_user: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="generated_reports",
    )
    
    def __repr__(self) -> str:
        return f"<Report {self.id} - Type: {self.report_type}>"
    
    def __str__(self) -> str:
        return f"Rapport {self.report_type} du {self.created_at}"
    
    @property
    def file_size_mb(self) -> Optional[float]:
        """Retourne la taille en MB"""
        return self.file_size / (1024 * 1024) if self.file_size else None
    
    @property
    def is_generated(self) -> bool:
        """Vérifie si le rapport est généré"""
        return self.status == "generated"
    
    @property
    def is_sent(self) -> bool:
        """Vérifie si le rapport a été envoyé"""
        return self.status == "sent" and self.sent_at is not None
    
    @property
    def filename(self) -> Optional[str]:
        """Retourne le nom du fichier"""
        if not self.file_path:
            return None
        return self.file_path.split("/")[-1]

