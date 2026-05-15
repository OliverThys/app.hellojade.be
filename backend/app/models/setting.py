"""
Modèle Setting pour la configuration système
"""
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class Setting(Base):
    """Modèle pour les paramètres système"""
    
    __tablename__ = "settings"
    
    # Colonnes
    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        nullable=False,
    )
    
    # Clé et valeur
    key: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
        comment="Clé unique du paramètre",
    )
    value: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        comment="Valeur du paramètre (JSON)",
    )
    
    # Catégorisation
    category: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        index=True,
        comment="Catégorie (system, asterisk, ai, notification, scheduler, etc.)",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Description du paramètre",
    )
    
    # Type et validation
    value_type: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="Type de valeur (string, number, boolean, object, array)",
    )
    validation_schema: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        comment="Schéma de validation JSON",
    )
    
    # Sécurité
    is_sensitive: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Indique si le paramètre contient des données sensibles",
    )
    encrypted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Indique si la valeur est chiffrée",
    )
    
    # Historique
    updated_by: Mapped[Optional[UUID]] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    previous_value: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        comment="Valeur précédente avant modification",
    )
    
    # Métadonnées
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
    updated_by_user: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[updated_by],
    )
    
    def __repr__(self) -> str:
        return f"<Setting {self.key} = {self.value}>"
    
    def __str__(self) -> str:
        return f"{self.key}: {self.value}"
    
    @property
    def is_system_critical(self) -> bool:
        """Vérifie si le paramètre est critique pour le système"""
        critical_keys = [
            "database_url",
            "redis_url",
            "secret_key",
        ]
        return self.key in critical_keys

    @property
    def requires_restart(self) -> bool:
        """Vérifie si la modification nécessite un redémarrage"""
        restart_keys = [
            "database_url",
            "redis_url",
            "asterisk_host",
            "asterisk_port",
        ]
        return self.key in restart_keys
    
    def get_value_as_string(self) -> str:
        """Retourne la valeur comme string"""
        if isinstance(self.value, str):
            return self.value
        if isinstance(self.value, dict) and "value" in self.value:
            return str(self.value["value"])
        return str(self.value)
    
    def get_value_as_int(self) -> Optional[int]:
        """Retourne la valeur comme entier"""
        try:
            if isinstance(self.value, int):
                return self.value
            if isinstance(self.value, dict) and "value" in self.value:
                return int(self.value["value"])
            return int(self.value)
        except (ValueError, TypeError):
            return None
    
    def get_value_as_bool(self) -> bool:
        """Retourne la valeur comme booléen"""
        if isinstance(self.value, bool):
            return self.value
        if isinstance(self.value, dict) and "value" in self.value:
            return bool(self.value["value"])
        return bool(self.value)


