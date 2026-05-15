"""
Modèle AuditLog pour la traçabilité RGPD
"""
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import INET, JSON, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class AuditLog(Base):
    """Modèle pour les logs d'audit (traçabilité RGPD)"""
    
    __tablename__ = "audit_logs"
    
    # Colonnes
    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        nullable=False,
    )
    
    # Utilisateur
    user_id: Mapped[Optional[UUID]] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_email: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Email de l'utilisateur au moment de l'action",
    )
    
    # Action
    action: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Type d'action (login, logout, view, create, update, delete, export, etc.)",
    )
    resource_type: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        index=True,
        comment="Type de ressource (patient, call, user, report, etc.)",
    )
    resource_id: Mapped[Optional[UUID]] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="ID de la ressource affectée",
    )
    resource_name: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="Nom ou description de la ressource",
    )
    
    # Détails
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        comment="Détails supplémentaires de l'action",
    )
    changes: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        comment="Changements effectués (before/after)",
    )
    
    # Contexte
    ip_address: Mapped[Optional[str]] = mapped_column(
        INET,
        nullable=True,
        comment="Adresse IP de l'utilisateur",
    )
    user_agent: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="User agent du navigateur",
    )
    session_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="ID de session",
    )
    
    # Métadonnées
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    
    # Relations ORM
    user: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="audit_logs",
    )
    
    def __repr__(self) -> str:
        return f"<AuditLog {self.id} - {self.action} by {self.user_email}>"
    
    def __str__(self) -> str:
        return f"{self.action} sur {self.resource_type} par {self.user_email} le {self.created_at}"
    
    @property
    def is_sensitive_action(self) -> bool:
        """Vérifie si l'action est sensible"""
        sensitive_actions = [
            "view_patient_data",
            "export_patient_data",
            "delete_patient_data",
            "view_medical_report",
            "access_recording",
            "modify_consent",
        ]
        return self.action in sensitive_actions
    
    @property
    def is_admin_action(self) -> bool:
        """Vérifie si c'est une action administrative"""
        admin_actions = [
            "create_user",
            "update_user",
            "delete_user",
            "change_permissions",
            "system_config",
            "backup",
            "restore",
        ]
        return self.action in admin_actions
    
    @property
    def is_gdpr_action(self) -> bool:
        """Vérifie si l'action est liée au RGPD"""
        gdpr_actions = [
            "export_patient_data",
            "delete_patient_data",
            "view_consent",
            "modify_consent",
            "data_access_request",
            "data_deletion_request",
        ]
        return self.action in gdpr_actions

