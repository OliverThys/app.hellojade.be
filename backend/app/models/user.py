"""
Modèle User pour les utilisateurs du système
"""
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.audit_log import AuditLog
    from app.models.call import Call
    from app.models.report import Report


class User(Base):
    """Modèle pour les utilisateurs (médecins, infirmiers, admins)"""
    
    __tablename__ = "users"
    
    # Colonnes
    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        nullable=False,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    username: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    full_name: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
    )
    role: Mapped[str] = mapped_column(
        Enum("admin", "medecin", "infirmier", "operateur", name="user_role"),
        nullable=False,
        default="operateur",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    last_login: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
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
    
    # Relations
    initiated_calls: Mapped[List["Call"]] = relationship(
        "Call",
        back_populates="initiated_by_user",
        cascade="all, delete-orphan",
    )
    generated_reports: Mapped[List["Report"]] = relationship(
        "Report",
        back_populates="generated_by_user",
        cascade="all, delete-orphan",
    )
    audit_logs: Mapped[List["AuditLog"]] = relationship(
        "AuditLog",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    
    def __repr__(self) -> str:
        return f"<User {self.username} ({self.email})>"
    
    def __str__(self) -> str:
        return self.full_name or self.username
    
    @property
    def is_admin(self) -> bool:
        """Vérifie si l'utilisateur est admin"""
        return self.role == "admin"
    
    @property
    def is_medical_staff(self) -> bool:
        """Vérifie si l'utilisateur fait partie du personnel médical"""
        return self.role in ["medecin", "infirmier"]
    
    @property
    def can_view_patients(self) -> bool:
        """Vérifie si l'utilisateur peut voir les patients"""
        return self.is_active and self.role != "operateur"
    
    @property
    def can_initiate_calls(self) -> bool:
        """Vérifie si l'utilisateur peut initier des appels"""
        return self.is_active
    
    @property
    def can_view_reports(self) -> bool:
        """Vérifie si l'utilisateur peut voir les rapports"""
        return self.is_active and (self.is_medical_staff or self.is_admin)
    
    @property
    def can_manage_users(self) -> bool:
        """Vérifie si l'utilisateur peut gérer d'autres utilisateurs"""
        return self.is_active and self.is_admin

