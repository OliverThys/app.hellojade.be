"""
Fonctions de sécurité et authentification
"""
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Union

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings


# Configuration du contexte de hachage des mots de passe
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=settings.BCRYPT_ROUNDS,
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Vérifie si un mot de passe en clair correspond au hash
    
    Args:
        plain_password: Mot de passe en clair
        hashed_password: Hash du mot de passe
    
    Returns:
        True si les mots de passe correspondent
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Hash un mot de passe
    
    Args:
        password: Mot de passe en clair
    
    Returns:
        Hash du mot de passe
    """
    return pwd_context.hash(password)


def create_access_token(
    subject: Union[str, Any],
    expires_delta: Optional[timedelta] = None,
    additional_claims: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Crée un token JWT d'accès
    
    Args:
        subject: Sujet du token (généralement l'ID utilisateur)
        expires_delta: Durée de validité du token
        additional_claims: Claims additionnels à inclure
    
    Returns:
        Token JWT encodé
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        )
    
    to_encode = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access",
    }
    
    if additional_claims:
        to_encode.update(additional_claims)
    
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    return encoded_jwt


def create_refresh_token(
    subject: Union[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Crée un token JWT de rafraîchissement
    
    Args:
        subject: Sujet du token (généralement l'ID utilisateur)
        expires_delta: Durée de validité du token
    
    Returns:
        Token JWT encodé
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
        )
    
    to_encode = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "refresh",
    }
    
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    return encoded_jwt


def decode_token(token: str) -> Dict[str, Any]:
    """
    Décode un token JWT
    
    Args:
        token: Token JWT à décoder
    
    Returns:
        Payload du token
    
    Raises:
        JWTError: Si le token est invalide
    """
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
    )


def verify_token(token: str, token_type: str = "access") -> Optional[str]:
    """
    Vérifie un token JWT et retourne le sujet
    
    Args:
        token: Token JWT à vérifier
        token_type: Type de token attendu ("access" ou "refresh")
    
    Returns:
        Sujet du token si valide, None sinon
    """
    try:
        payload = decode_token(token)
        
        # Vérifier le type de token
        if payload.get("type") != token_type:
            return None
        
        # Extraire le sujet
        subject: str = payload.get("sub")
        if subject is None:
            return None
        
        return subject
        
    except JWTError:
        return None


def generate_password_reset_token(email: str) -> str:
    """
    Génère un token pour la réinitialisation de mot de passe
    
    Args:
        email: Email de l'utilisateur
    
    Returns:
        Token de réinitialisation
    """
    expire = datetime.utcnow() + timedelta(hours=24)
    to_encode = {
        "sub": email,
        "exp": expire,
        "type": "password_reset",
    }
    return jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def verify_password_reset_token(token: str) -> Optional[str]:
    """
    Vérifie un token de réinitialisation de mot de passe
    
    Args:
        token: Token à vérifier
    
    Returns:
        Email de l'utilisateur si valide, None sinon
    """
    try:
        payload = decode_token(token)
        
        # Vérifier le type de token
        if payload.get("type") != "password_reset":
            return None
        
        # Extraire l'email
        email: str = payload.get("sub")
        return email
        
    except JWTError:
        return None

