"""
Schémas Pydantic pour les unités de soins
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CareUnitCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    service_code: str = Field(..., min_length=1, max_length=50)
    phone_number: Optional[str] = Field(None, max_length=20)
    transfer_number: Optional[str] = Field(None, max_length=20)
    is_active: bool = True
    description: Optional[str] = None


class CareUnitUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=150)
    service_code: Optional[str] = Field(None, min_length=1, max_length=50)
    phone_number: Optional[str] = Field(None, max_length=20)
    transfer_number: Optional[str] = Field(None, max_length=20)
    is_active: Optional[bool] = None
    description: Optional[str] = None


class CareUnitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    service_code: str
    phone_number: Optional[str] = None
    transfer_number: Optional[str] = None
    is_active: bool
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
