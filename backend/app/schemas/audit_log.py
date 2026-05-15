"""
Schémas Pydantic pour les logs d'audit
"""
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AuditLogCreate(BaseModel):
    """Schéma pour la création d'un log d'audit"""
    
    user_id: Optional[UUID] = None
    user_email: Optional[str] = Field(None, max_length=255)
    action: str = Field(..., max_length=100)
    resource_type: Optional[str] = Field(None, max_length=50)
    resource_id: Optional[UUID] = None
    resource_name: Optional[str] = Field(None, max_length=200)
    details: Optional[Dict[str, Any]] = None
    changes: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    session_id: Optional[str] = Field(None, max_length=100)


class AuditLogResponse(BaseModel):
    """Schéma de réponse pour un log d'audit"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: Optional[UUID] = None
    user_email: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[UUID] = None
    resource_name: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    changes: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None

    @field_validator("ip_address", mode="before")
    @classmethod
    def convert_ip_to_str(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        return str(v)
    user_agent: Optional[str] = None
    session_id: Optional[str] = None
    created_at: datetime
    
    # Propriétés calculées
    is_sensitive_action: bool = False
    is_admin_action: bool = False
    is_gdpr_action: bool = False


class AuditLogInDB(BaseModel):
    """Schéma pour un log d'audit en base de données"""
    
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    user_id: Optional[UUID] = None
    user_email: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[UUID] = None
    resource_name: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    changes: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    session_id: Optional[str] = None
    created_at: datetime

