"""
Dépendances FastAPI communes
"""
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_token
from app.database import get_db
from app.models.user import User


# Security scheme
security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Récupère l'utilisateur courant depuis le token JWT
    
    Args:
        credentials: Credentials HTTP Bearer
        db: Session de base de données
        
    Returns:
        Utilisateur courant
        
    Raises:
        HTTPException: Si le token est invalide ou l'utilisateur n'existe pas
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token d'authentification manquant",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        # Décoder le token
        payload = decode_token(credentials.credentials)
        
        # Vérifier le type de token
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Type de token invalide",
            )
        
        # Récupérer l'ID utilisateur
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token invalide",
            )
            
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expiré",
        )
    
    # Récupérer l'utilisateur depuis la base
    user = await db.get(User, UUID(user_id))
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouvé",
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte utilisateur désactivé",
        )
    
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Vérifie que l'utilisateur courant est actif
    
    Args:
        current_user: Utilisateur courant
        
    Returns:
        Utilisateur actif
        
    Raises:
        HTTPException: Si l'utilisateur n'est pas actif
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte utilisateur désactivé",
        )
    return current_user


async def get_current_admin_user(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    Vérifie que l'utilisateur courant est admin
    
    Args:
        current_user: Utilisateur courant actif
        
    Returns:
        Utilisateur admin
        
    Raises:
        HTTPException: Si l'utilisateur n'est pas admin
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions administrateur requises",
        )
    return current_user


async def get_current_medical_user(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    Vérifie que l'utilisateur courant est personnel médical
    
    Args:
        current_user: Utilisateur courant actif
        
    Returns:
        Utilisateur médical
        
    Raises:
        HTTPException: Si l'utilisateur n'est pas personnel médical
    """
    if not current_user.is_medical_staff:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions médicales requises",
        )
    return current_user


def get_optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """
    Récupère l'utilisateur courant si un token est fourni (optionnel)
    
    Args:
        credentials: Credentials HTTP Bearer (optionnel)
        db: Session de base de données
        
    Returns:
        Utilisateur courant ou None
    """
    if not credentials:
        return None
    
    try:
        # Décoder le token
        payload = decode_token(credentials.credentials)
        
        # Vérifier le type de token
        if payload.get("type") != "access":
            return None
        
        # Récupérer l'ID utilisateur
        user_id = payload.get("sub")
        if user_id is None:
            return None
            
    except JWTError:
        return None
    
    # Récupérer l'utilisateur depuis la base
    user = db.get(User, UUID(user_id))
    
    if user is None or not user.is_active:
        return None
    
    return user


# Pagination
class PaginationParams:
    """Paramètres de pagination"""
    
    def __init__(
        self,
        skip: int = 0,
        limit: int = 50,
    ):
        self.skip = skip
        self.limit = min(limit, 100)  # Limiter à 100 max


def get_pagination(
    skip: int = 0,
    limit: int = 50,
) -> PaginationParams:
    """
    Obtient les paramètres de pagination
    
    Args:
        skip: Nombre d'éléments à ignorer
        limit: Nombre maximum d'éléments à retourner
        
    Returns:
        Paramètres de pagination
    """
    return PaginationParams(skip=skip, limit=limit)

