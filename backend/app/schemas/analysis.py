"""
Schémas Pydantic pour les analyses IA
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field


class AnalysisBase(BaseModel):
    """Schéma de base pour les analyses"""

    # Nouveaux champs - Questionnaire de suivi postopératoire
    # 1. Douleur
    has_pain: Optional[bool] = None
    pain_level: Optional[int] = Field(None, ge=0, le=10)
    pain_relieved: Optional[bool] = None

    # 2. Alimentation
    eating_normally: Optional[bool] = None
    eating_difficulty_score: Optional[int] = Field(None, ge=0, le=10)
    drinking_possible: Optional[bool] = None

    # 3. Nausées / Vomissements
    has_nausea: Optional[bool] = None
    nausea_severity_score: Optional[int] = Field(None, ge=0, le=10)
    blood_in_vomit: Optional[bool] = None

    # 4. Maux de tête
    has_headache: Optional[bool] = None
    headache_level: Optional[int] = Field(None, ge=0, le=10)

    # 5. Saignements
    has_bleeding: Optional[bool] = None
    bleeding_abundance_score: Optional[int] = Field(None, ge=0, le=10)
    bleeding_stopped: Optional[bool] = None
    infection_signs: Optional[bool] = None

    # 6. Contact médical
    contacted_emergency: Optional[bool] = None
    emergency_reason: Optional[str] = None

    # 7. Consignes postopératoires
    understands_instructions: Optional[bool] = None
    instruction_doubts: Optional[str] = None

    # Anciens champs (compatibilité ascendante - DEPRECATED)
    pain_location: Optional[str] = Field(None, max_length=200)
    pain_description: Optional[str] = None
    has_fever: Optional[bool] = None
    fever_temperature: Optional[float] = Field(None, ge=35.0, le=42.0)
    fever_duration: Optional[str] = Field(None, max_length=100)
    takes_medication: Optional[bool] = None
    medication_regularity: Optional[str] = Field(None, max_length=50)
    medication_issues: Optional[str] = None
    moral_state: Optional[int] = Field(None, ge=1, le=5)
    moral_description: Optional[str] = None

    # Analyse IA
    summary: Optional[str] = None
    alerts: Optional[List[Dict[str, Any]]] = None
    recommendations: Optional[List[str]] = None
    risk_score: int = Field(default=0, ge=0, le=10)


class AnalysisCreate(AnalysisBase):
    """Schéma pour la création d'une analyse"""
    
    call_id: UUID
    transcription_id: Optional[UUID] = None
    model_used: str = "llama3.1:8b"
    processing_time: Optional[float] = Field(None, ge=0.0)
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    raw_response: Optional[Dict[str, Any]] = None


class AnalysisUpdate(BaseModel):
    """Schéma pour la mise à jour d'une analyse"""

    model_config = ConfigDict(validate_assignment=True)

    # Nouveaux champs - Questionnaire de suivi postopératoire
    has_pain: Optional[bool] = None
    pain_level: Optional[int] = Field(None, ge=0, le=10)
    pain_relieved: Optional[bool] = None
    eating_normally: Optional[bool] = None
    eating_difficulty_score: Optional[int] = Field(None, ge=0, le=10)
    drinking_possible: Optional[bool] = None
    has_nausea: Optional[bool] = None
    nausea_severity_score: Optional[int] = Field(None, ge=0, le=10)
    blood_in_vomit: Optional[bool] = None
    has_headache: Optional[bool] = None
    headache_level: Optional[int] = Field(None, ge=0, le=10)
    has_bleeding: Optional[bool] = None
    bleeding_abundance_score: Optional[int] = Field(None, ge=0, le=10)
    bleeding_stopped: Optional[bool] = None
    infection_signs: Optional[bool] = None
    contacted_emergency: Optional[bool] = None
    emergency_reason: Optional[str] = None
    understands_instructions: Optional[bool] = None
    instruction_doubts: Optional[str] = None

    # Anciens champs (DEPRECATED)
    pain_location: Optional[str] = Field(None, max_length=200)
    pain_description: Optional[str] = None
    has_fever: Optional[bool] = None
    fever_temperature: Optional[float] = Field(None, ge=35.0, le=42.0)
    fever_duration: Optional[str] = Field(None, max_length=100)
    takes_medication: Optional[bool] = None
    medication_regularity: Optional[str] = Field(None, max_length=50)
    medication_issues: Optional[str] = None
    moral_state: Optional[int] = Field(None, ge=1, le=5)
    moral_description: Optional[str] = None

    summary: Optional[str] = None
    alerts: Optional[List[Dict[str, Any]]] = None
    recommendations: Optional[List[str]] = None
    risk_score: Optional[int] = Field(None, ge=0, le=10)


class AnalysisResponse(AnalysisBase):
    """Schéma de réponse pour une analyse"""
    
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    call_id: UUID
    transcription_id: Optional[UUID] = None
    model_used: str
    processing_time: Optional[float] = None
    confidence: Optional[float] = None
    created_at: datetime

    @computed_field
    @property
    def has_critical_alerts(self) -> bool:
        """Vérifie s'il y a des alertes critiques"""
        if not self.alerts:
            return False
        return any(alert.get("severity") == "urgent" for alert in self.alerts)

    @computed_field
    @property
    def has_warnings(self) -> bool:
        """Vérifie s'il y a des avertissements"""
        if not self.alerts:
            return False
        return any(alert.get("severity") == "warning" for alert in self.alerts)

    @computed_field
    @property
    def alert_count(self) -> int:
        """Retourne le nombre d'alertes"""
        return len(self.alerts) if self.alerts else 0

    @computed_field
    @property
    def is_high_risk(self) -> bool:
        """Vérifie si le patient est à haut risque"""
        return self.risk_score >= 7 if self.risk_score else False

    @computed_field
    @property
    def requires_medical_attention(self) -> bool:
        """Vérifie si une attention médicale est requise"""
        return (
            self.has_critical_alerts
            or (self.risk_score >= 8 if self.risk_score else False)
            or (self.fever_temperature and self.fever_temperature >= 38.5)
            or (self.pain_level and self.pain_level >= 8)
        )

    @computed_field
    @property
    def medication_compliance_score(self) -> Optional[int]:
        """Calcule un score de compliance médicamenteuse"""
        if self.takes_medication is None:
            return None
        if not self.takes_medication:
            return 0
        if self.medication_regularity == "toujours":
            return 10
        elif self.medication_regularity == "souvent":
            return 7
        elif self.medication_regularity == "parfois":
            return 4
        else:
            return 2


class AnalysisInDB(AnalysisBase):
    """Schéma pour une analyse en base de données"""
    
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    call_id: UUID
    transcription_id: Optional[UUID] = None
    model_used: str
    processing_time: Optional[float] = None
    confidence: Optional[float] = None
    raw_response: Optional[Dict[str, Any]] = None
    created_at: datetime

