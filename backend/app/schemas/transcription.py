"""
Schémas Pydantic pour les transcriptions
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TranscriptionCreate(BaseModel):
    """Schéma pour la création d'une transcription"""
    
    call_id: UUID
    full_text: str
    language: str = "fr-BE"
    whisper_model: str = "large-v3"
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    segments: Optional[Dict[str, Any]] = None
    processing_time: Optional[float] = Field(None, ge=0.0)


class TranscriptionResponse(BaseModel):
    """Schéma de réponse pour une transcription"""
    
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    call_id: UUID
    full_text: str
    language: str
    whisper_model: str
    confidence: Optional[float] = None
    segments: Optional[Dict[str, Any]] = None
    processing_time: Optional[float] = None
    created_at: datetime
    
    # Propriétés calculées
    word_count: int = 0
    char_count: int = 0
    segment_count: int = 0
    has_high_confidence: bool = False
    summary: str = ""


class TranscriptionInDB(BaseModel):
    """Schéma pour une transcription en base de données"""
    
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    call_id: UUID
    full_text: str
    language: str
    whisper_model: str
    confidence: Optional[float] = None
    segments: Optional[Dict[str, Any]] = None
    processing_time: Optional[float] = None
    created_at: datetime

