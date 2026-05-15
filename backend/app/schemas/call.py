"""
Schémas Pydantic pour les appels téléphoniques
"""
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.analysis import AnalysisResponse
from app.schemas.transcription import TranscriptionResponse
from app.schemas.patient import PatientResponse


class CallBase(BaseModel):
    """Schéma de base pour les appels"""
    
    caller_number: str = Field(..., max_length=20)
    callee_number: str = Field(..., max_length=20)
    notes: Optional[str] = None


class CallCreate(CallBase):
    """Schéma pour la création d'un appel"""
    
    patient_id: UUID
    initiated_by: Optional[UUID] = None


class CallUpdate(BaseModel):
    """Schéma pour la mise à jour d'un appel"""
    
    model_config = ConfigDict(validate_assignment=True)
    
    status: Optional[str] = Field(
        None,
        pattern="^(pending|ringing|in_progress|completed|failed|no_answer|busy|cancelled|interrupted)$"
    )
    asterisk_call_id: Optional[str] = Field(None, max_length=100)
    asterisk_channel: Optional[str] = Field(None, max_length=200)
    start_time: Optional[datetime] = None
    answer_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration: Optional[int] = Field(None, ge=0)
    recording_path: Optional[str] = Field(None, max_length=500)
    recording_size: Optional[int] = Field(None, ge=0)
    failure_reason: Optional[str] = Field(None, max_length=200)
    notes: Optional[str] = None


class CallResponse(CallBase):
    """Schéma de réponse pour un appel"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: Optional[UUID] = None
    initiated_by: Optional[UUID] = None
    asterisk_call_id: Optional[str] = None
    asterisk_channel: Optional[str] = None
    status: str
    start_time: Optional[datetime] = None
    answer_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration: Optional[int] = None
    recording_path: Optional[str] = None
    recording_size: Optional[int] = None
    failure_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    # Propriétés calculées
    duration_minutes: Optional[float] = None
    is_successful: bool = False
    is_failed: bool = False
    has_transcription: bool = False
    has_analysis: bool = False
    has_recording: bool = False
    recording_size_mb: Optional[float] = None
    
    # Données ARI : réponses, transcriptions, alertes
    call_metadata: Optional[Dict[str, Any]] = None

    # Relation patient (optionnelle, chargée si disponible)
    patient: Optional[PatientResponse] = None


class CallWithAnalysis(CallResponse):
    """Schéma de réponse pour un appel avec analyse"""
    
    transcription: Optional[TranscriptionResponse] = None
    analysis: Optional[AnalysisResponse] = None


class CallInDB(CallBase):
    """Schéma pour un appel en base de données"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: Optional[UUID] = None
    initiated_by: Optional[UUID] = None
    asterisk_call_id: Optional[str] = None
    asterisk_channel: Optional[str] = None
    status: str
    start_time: Optional[datetime] = None
    answer_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration: Optional[int] = None
    recording_path: Optional[str] = None
    recording_size: Optional[int] = None
    failure_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

