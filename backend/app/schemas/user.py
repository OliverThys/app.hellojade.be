"""
Schémas Pydantic pour les utilisateurs
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserBase(BaseModel):
    """Schéma de base pour les utilisateurs"""
    
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=100)
    full_name: Optional[str] = Field(None, max_length=200)
    role: str = Field(default="operateur", pattern="^(admin|medecin|infirmier|operateur)$")
    is_active: bool = True


class UserCreate(UserBase):
    """Schéma pour la création d'un utilisateur"""
    
    password: str = Field(..., min_length=8, max_length=100)
    
    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Valide la complexité du mot de passe"""
        if len(v) < 8:
            raise ValueError("Le mot de passe doit contenir au moins 8 caractères")
        if not any(char.isdigit() for char in v):
            raise ValueError("Le mot de passe doit contenir au moins un chiffre")
        if not any(char.isupper() for char in v):
            raise ValueError("Le mot de passe doit contenir au moins une majuscule")
        if not any(char.islower() for char in v):
            raise ValueError("Le mot de passe doit contenir au moins une minuscule")
        return v


class UserUpdate(BaseModel):
    """Schéma pour la mise à jour d'un utilisateur"""
    
    model_config = ConfigDict(validate_assignment=True)
    
    email: Optional[EmailStr] = None
    username: Optional[str] = Field(None, min_length=3, max_length=100)
    full_name: Optional[str] = Field(None, max_length=200)
    role: Optional[str] = Field(None, pattern="^(admin|medecin|infirmier|operateur)$")
    is_active: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=8, max_length=100)


class UserLogin(BaseModel):
    """Schéma pour la connexion d'un utilisateur"""
    
    username: str
    password: str


class UserResponse(UserBase):
    """Schéma de réponse pour un utilisateur"""
    
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    last_login: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    
    # Propriétés calculées
    is_admin: bool = False
    is_medical_staff: bool = False
    can_view_patients: bool = False
    can_initiate_calls: bool = False
    can_view_reports: bool = False
    can_manage_users: bool = False
    
    @classmethod
    def from_orm_with_permissions(cls, user) -> "UserResponse":
        """Crée une réponse avec les permissions calculées"""
        return cls(
            id=user.id,
            email=user.email,
            username=user.username,
            full_name=user.full_name,
            role=user.role,
            is_active=user.is_active,
            last_login=user.last_login,
            created_at=user.created_at,
            updated_at=user.updated_at,
            is_admin=user.is_admin,
            is_medical_staff=user.is_medical_staff,
            can_view_patients=user.can_view_patients,
            can_initiate_calls=user.can_initiate_calls,
            can_view_reports=user.can_view_reports,
            can_manage_users=user.can_manage_users,
        )


class UserInDB(UserBase):
    """Schéma pour un utilisateur en base de données"""
    
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    hashed_password: str
    last_login: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

