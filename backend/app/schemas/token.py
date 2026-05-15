"""
Schémas Pydantic pour les tokens JWT
"""
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class Token(BaseModel):
    """Schéma pour la réponse de token"""
    
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    """Corps JSON pour POST /auth/refresh (même contrat que le frontend)."""

    refresh_token: str


class TokenPayload(BaseModel):
    """Schéma pour le payload d'un token JWT"""
    
    sub: Optional[UUID] = None
    exp: Optional[int] = None
    iat: Optional[int] = None
    type: Optional[str] = None
    role: Optional[str] = None
    
    # Claims additionnels optionnels
    email: Optional[str] = None
    username: Optional[str] = None
    is_active: Optional[bool] = None

