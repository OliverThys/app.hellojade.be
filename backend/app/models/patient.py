"""
Modèle Patient pour les patients suivis
"""
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.call import Call
    from app.models.document import PatientDocument


class Patient(Base):
    """Modèle pour les patients (copie locale depuis Oracle)"""
    
    __tablename__ = "patients"
    
    # Colonnes
    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        nullable=False,
    )
    oracle_patient_id: Mapped[int] = mapped_column(
        Integer,
        unique=True,
        nullable=False,
        index=True,
        comment="ID du patient dans la base Oracle",
    )
    numero_dossier: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
    )
    nom: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    prenom: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    telephone: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        index=True,
    )
    email: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    date_naissance: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
    )
    sexe: Mapped[Optional[str]] = mapped_column(
        String(1),
        nullable=True,
    )
    adresse: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
    )
    ville: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    code_postal: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
    )
    
    # Informations médicales
    service_hospitalisation: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    date_admission: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
    )
    date_sortie: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
    )
    diagnostic_principal: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    medecin_responsable: Mapped[Optional[str]] = mapped_column(
        String(150),
        nullable=True,
    )
    
    # Statut et suivi
    status: Mapped[str] = mapped_column(
        Enum("actif", "inactif", "prioritaire", "urgence", name="patient_status"),
        default="actif",
        nullable=False,
        index=True,
    )
    last_call_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    next_call_scheduled: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    risk_score: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        index=True,
    )
    
    # RGPD
    consent_given: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    consent_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    # Notes
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    # Rappel manuel
    manually_recalled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
        comment="True = rappelé manuellement, bloque les retries automatiques JADE",
    )
    manually_recalled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    manually_recalled_by: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="Nom du soignant qui a effectué le rappel (depuis IntraID)",
    )
    callback_note: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Note rédigée par le soignant lors du rappel manuel",
    )
    
    # HL7 / Epicura
    sejour_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        index=True,
        comment="Identifiant séjour (PV1.19.1 HL7)",
    )
    visite_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Identifiant visite (PV1.19.2 HL7)",
    )
    hl7_source: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Source de l'import (ex: ADT_MIRTH)",
    )

    # Métadonnées
    last_sync_oracle: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Dernière synchronisation avec Oracle",
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
    calls: Mapped[List["Call"]] = relationship(
        "Call",
        back_populates="patient",
        cascade="all, delete-orphan",
        order_by="desc(Call.created_at)",
    )
    documents: Mapped[List["PatientDocument"]] = relationship(
        "PatientDocument",
        back_populates="patient",
        cascade="all, delete-orphan",
        order_by="desc(PatientDocument.uploaded_at)",
    )

    def __repr__(self) -> str:
        return f"<Patient {self.nom} {self.prenom} ({self.numero_dossier})>"
    
    def __str__(self) -> str:
        return f"{self.nom} {self.prenom}"
    
    @property
    def full_name(self) -> str:
        """Retourne le nom complet du patient"""
        return f"{self.prenom} {self.nom}"
    
    @property
    def age(self) -> Optional[int]:
        """Calcule l'âge du patient"""
        if not self.date_naissance:
            return None
        today = datetime.now()
        age = today.year - self.date_naissance.year
        if (today.month, today.day) < (self.date_naissance.month, self.date_naissance.day):
            age -= 1
        return age
    
    @property
    def days_since_discharge(self) -> Optional[int]:
        """Nombre de jours depuis la sortie"""
        if not self.date_sortie:
            return None
        return (datetime.now() - self.date_sortie).days
    
    @property
    def is_priority(self) -> bool:
        """Vérifie si le patient est prioritaire"""
        return self.status in ["prioritaire", "urgence"] or self.risk_score >= 7
    
    @property
    def can_be_called(self) -> bool:
        """Vérifie si le patient peut être appelé"""
        return (
            self.status == "actif"
            and self.consent_given
            and self.telephone is not None
        )
    
    @property
    def requires_immediate_attention(self) -> bool:
        """Vérifie si le patient nécessite une attention immédiate"""
        return self.status == "urgence" or self.risk_score >= 9

