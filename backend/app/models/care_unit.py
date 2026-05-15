"""
Modèle CareUnit pour les unités de soins hospitalières
"""
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CareUnit(Base):
    """Unité de soins avec numéros de téléphone pour transfert d'appel"""

    __tablename__ = "care_units"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        index=True,
        comment="Nom de l'unité de soins (ex: Chirurgie orthopédique)",
    )
    service_code: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        comment="Code service hospitalier (correspond au PV1.3 HL7)",
    )
    phone_number: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="Numéro principal de l'unité",
    )
    transfer_number: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="Numéro de transfert d'appel (utilisé par Q7)",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
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

    def __repr__(self) -> str:
        return f"<CareUnit {self.name} ({self.service_code})>"
