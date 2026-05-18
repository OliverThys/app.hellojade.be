"""
Schémas Pydantic pour les patients
"""
from datetime import datetime
from typing import Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


def parse_date(value: Optional[Union[str, datetime]]) -> Optional[datetime]:
    """Parse une date depuis string (YYYY-MM-DD) ou datetime, sans timezone"""
    if value is None:
        return None
    if isinstance(value, datetime):
        # Si c'est déjà un datetime, retirer le timezone s'il existe
        if value.tzinfo is not None:
            return value.replace(tzinfo=None)
        return value
    if isinstance(value, str):
        # Parser YYYY-MM-DD ou YYYY-MM-DDTHH:MM:SS
        try:
            if 'T' in value:
                dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            else:
                dt = datetime.fromisoformat(value)
            # Retirer le timezone si présent
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt
        except (ValueError, AttributeError):
            return None
    return None


class PatientBase(BaseModel):
    """Schéma de base pour les patients"""
    
    numero_dossier: str = Field(..., min_length=1, max_length=50)
    nom: str = Field(..., min_length=1, max_length=100)
    prenom: str = Field(..., min_length=1, max_length=100)
    telephone: Optional[str] = Field(None, max_length=20)
    email: Optional[EmailStr] = None
    date_naissance: Optional[datetime] = None
    sexe: Optional[str] = Field(None, pattern="^[MF]$")
    adresse: Optional[str] = Field(None, max_length=200)
    ville: Optional[str] = Field(None, max_length=100)
    code_postal: Optional[str] = Field(None, max_length=10)
    
    # Informations médicales
    service_hospitalisation: Optional[str] = Field(None, max_length=100)
    date_admission: Optional[datetime] = None
    date_sortie: Optional[datetime] = None
    diagnostic_principal: Optional[str] = Field(None, max_length=500)
    medecin_responsable: Optional[str] = Field(None, max_length=150)
    
    @field_validator('date_naissance', 'date_admission', 'date_sortie', mode='before')
    @classmethod
    def parse_date_fields(cls, v: Optional[Union[str, datetime]]) -> Optional[datetime]:
        return parse_date(v)


class PatientCreate(PatientBase):
    """Schéma pour la création d'un patient"""
    
    oracle_patient_id: int
    status: str = "actif"
    consent_given: bool = False
    notes: Optional[str] = None


class CallbackNoteUpdate(BaseModel):
    """Schéma pour la mise à jour de la note de rappel"""
    note: Optional[str] = None


class PatientUpdate(BaseModel):
    """Schéma pour la mise à jour d'un patient"""
    
    model_config = ConfigDict(validate_assignment=True)

    # Note rappel manuel : peut être mise à jour seule (voir endpoint PATCH /{patient_id})
    callback_note: Optional[str] = None
    
    telephone: Optional[str] = Field(None, max_length=20)
    email: Optional[EmailStr] = None
    adresse: Optional[str] = Field(None, max_length=200)
    ville: Optional[str] = Field(None, max_length=100)
    code_postal: Optional[str] = Field(None, max_length=10)
    status: Optional[str] = Field(None, pattern="^(actif|inactif|prioritaire|urgence)$")
    risk_score: Optional[int] = Field(None, ge=0, le=10)
    consent_given: Optional[bool] = None
    consent_date: Optional[datetime] = None
    notes: Optional[str] = None
    next_call_scheduled: Optional[datetime] = None


class PatientResponse(PatientBase):
    """Schéma de réponse pour un patient"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    oracle_patient_id: int
    status: str
    last_call_at: Optional[datetime] = None
    next_call_scheduled: Optional[datetime] = None
    risk_score: int
    consent_given: bool
    consent_date: Optional[datetime] = None
    notes: Optional[str] = None
    manually_recalled: bool = False
    manually_recalled_at: Optional[datetime] = None
    manually_recalled_by: Optional[str] = None
    callback_note: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    # Propriétés calculées
    age: Optional[int] = None
    days_since_discharge: Optional[int] = None
    is_priority: bool = False
    can_be_called: bool = False
    requires_immediate_attention: bool = False


class ManualRecallRequest(BaseModel):
    """Corps de la requête pour marquer un patient comme rappelé manuellement"""
    note: Optional[str] = None


class CallbackPatientItem(BaseModel):
    """Patient enrichi avec les infos du dernier appel pour la vue Rappels"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nom: str
    prenom: str
    telephone: Optional[str] = None
    service_hospitalisation: Optional[str] = None
    date_sortie: Optional[datetime] = None
    manually_recalled: bool = False
    manually_recalled_at: Optional[datetime] = None
    manually_recalled_by: Optional[str] = None
    callback_note: Optional[str] = None
    last_call_at: Optional[datetime] = None
    last_call_id: Optional[UUID] = None
    # Infos du dernier appel
    last_call_status: Optional[str] = None
    last_call_alert_triggered: Optional[bool] = None
    last_call_alert_type: Optional[str] = None
    last_call_alert_reason: Optional[str] = None
    # Libellé de la question ayant déclenché l'alerte clinique (pour la vue Rappels)
    last_call_alert_question: Optional[str] = None
    # Dernière modification du dossier patient (ex. mise à jour de la note de rappel)
    updated_at: Optional[datetime] = None
    # Tentatives d'appel non-joints consécutives (0=inconnu, 1=rappel auto prévu, >=2=définitif)
    call_attempt_count: int = 0


class CallbacksResponse(BaseModel):
    """Réponse de l'endpoint /callbacks — 4 catégories"""
    to_recall: list[CallbackPatientItem]
    ok: list[CallbackPatientItem]
    unreachable: list[CallbackPatientItem]
    manually_recalled: list[CallbackPatientItem]


class PatientInDB(PatientBase):
    """Schéma pour un patient en base de données"""
    
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    oracle_patient_id: int
    status: str
    last_call_at: Optional[datetime] = None
    next_call_scheduled: Optional[datetime] = None
    risk_score: int
    consent_given: bool
    consent_date: Optional[datetime] = None
    notes: Optional[str] = None
    last_sync_oracle: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

