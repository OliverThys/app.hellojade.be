"""
Schémas Pydantic pour les rapports
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field


class ReportCreate(BaseModel):
    """Schéma pour la création d'un rapport"""

    call_id: UUID
    analysis_id: Optional[UUID] = None
    report_type: str = "standard"
    generated_by: Optional[UUID] = None


# Schémas imbriqués pour les relations
class PatientBasic(BaseModel):
    """Schéma basique pour un patient"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nom: Optional[str] = None
    prenom: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    telephone: Optional[str] = None
    phone_number: Optional[str] = None
    numero_dossier: Optional[str] = None


class CallBasic(BaseModel):
    """Schéma basique pour un appel"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    callee_number: str
    created_at: datetime
    duration: Optional[int] = None
    patient: Optional[PatientBasic] = None


class AnalysisBasic(BaseModel):
    """Schéma basique pour une analyse"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    risk_score: Optional[int] = None
    summary: Optional[str] = None
    alerts: Optional[list] = None


class UserBasic(BaseModel):
    """Schéma basique pour un utilisateur"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: Optional[str] = None


class ReportResponse(BaseModel):
    """Schéma de réponse pour un rapport"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    call_id: UUID
    analysis_id: Optional[UUID] = None
    generated_by: Optional[UUID] = None
    report_type: str
    file_path: str
    file_size: Optional[int] = None
    file_hash: Optional[str] = None
    status: str
    sent_to: Optional[str] = None
    sent_at: Optional[datetime] = None
    created_at: datetime

    # Relations
    call: Optional[CallBasic] = None
    analysis: Optional[AnalysisBasic] = None
    generated_by_user: Optional[UserBasic] = None

    @computed_field
    @property
    def file_size_mb(self) -> Optional[float]:
        """Retourne la taille en MB"""
        return self.file_size / (1024 * 1024) if self.file_size else None

    @computed_field
    @property
    def is_generated(self) -> bool:
        """Vérifie si le rapport est généré"""
        return self.status == "generated"

    @computed_field
    @property
    def is_sent(self) -> bool:
        """Vérifie si le rapport a été envoyé"""
        return self.status == "sent" and self.sent_at is not None

    @computed_field
    @property
    def filename(self) -> Optional[str]:
        """Retourne le nom du fichier"""
        if not self.file_path:
            return None
        return self.file_path.split("/")[-1]

    @computed_field
    @property
    def risk_level(self) -> Optional[str]:
        """Détermine le niveau de risque basé sur le risk_score"""
        if not self.analysis or self.analysis.risk_score is None:
            return None
        score = self.analysis.risk_score
        if score < 4:
            return "low"
        elif score < 7:
            return "medium"
        elif score < 9:
            return "high"
        else:
            return "critical"


class ReportInDB(BaseModel):
    """Schéma pour un rapport en base de données"""
    
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    call_id: UUID
    analysis_id: Optional[UUID] = None
    generated_by: Optional[UUID] = None
    report_type: str
    file_path: str
    file_size: Optional[int] = None
    file_hash: Optional[str] = None
    status: str
    sent_to: Optional[str] = None
    sent_at: Optional[datetime] = None
    created_at: datetime

