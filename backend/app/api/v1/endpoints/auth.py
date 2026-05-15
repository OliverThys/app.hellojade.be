"""
Endpoints d'authentification - IntraID (SAML2) uniquement
"""
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from starlette.requests import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    verify_token,
)
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.token import RefreshTokenRequest, Token
from app.schemas.user import UserResponse
from app.services.audit_service import audit_service
from app.services.saml_service import build_saml_auth, extract_user_info_from_auth, map_groups_to_role


router = APIRouter()


@router.get("/saml/login")
async def saml_login(
    request: Request,
) -> Any:
    """
    Point d'entrée pour l'authentification SAML2 (Intra ID).

    Redirige l'utilisateur vers l'IdP si SAML2 est activé.
    """
    saml_auth = await build_saml_auth(request)
    # URL de redirection vers l'IdP (force_authn=True pour toujours redemander les identifiants)
    redirect_url = saml_auth.login(force_authn=True)
    return RedirectResponse(url=redirect_url)


@router.post("/saml/acs")
@router.get("/saml/acs")
async def saml_acs(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Assertion Consumer Service (ACS) pour SAML2.

    - Récupère et valide l'assertion SAML envoyée par l'IdP
    - Crée ou met à jour l'utilisateur local
    - Retourne des tokens JWT pour le frontend
    """
    saml_auth = await build_saml_auth(request)
    saml_auth.process_response()

    errors = saml_auth.get_errors()
    if errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erreur SAML2: {', '.join(errors)}",
        )

    if not saml_auth.is_authenticated():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentification SAML2 échouée.",
        )

    user_info = extract_user_info_from_auth(saml_auth)
    email = user_info.get("email")
    full_name = user_info.get("full_name") or email
    groups = user_info.get("groups", [])

    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="L'assertion SAML2 ne contient pas d'email utilisateur.",
        )

    # Mapper les groupes AD/IntraID vers un rôle HelloJADE
    role = map_groups_to_role(groups)

    # Chercher un utilisateur existant par email
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    user: Optional[User] = result.scalar_one_or_none()

    # Si non existant, créer un utilisateur "lié à Intra ID"
    if not user:
        base_username = email.split("@")[0]
        username = base_username

        # Éviter les collisions de username (ex: "admin" peut déjà exister)
        suffix = 0
        while True:
            existing = await db.execute(
                select(User).where(User.username == username)
            )
            if not existing.scalar_one_or_none():
                break
            suffix += 1
            username = f"{base_username}_{suffix}"

        user = User(
            email=email,
            username=username,
            full_name=full_name,
            hashed_password=get_password_hash("!disabled_saml_only!"),
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    else:
        # Mettre à jour le rôle si le groupe AD a changé
        if user.role != role:
            user.role = role
        if full_name and user.full_name != full_name:
            user.full_name = full_name

    # Mettre à jour les métadonnées utiles (last_login)
    user.last_login = datetime.utcnow()
    await db.commit()

    # Logger la connexion SAML réussie
    await audit_service.log_action(
        db=db,
        action="login",
        user_id=user.id,
        user_email=user.email,
        details={"login_method": "saml2", "groups": groups, "role": role},
        request=request,
    )

    # Créer les tokens JWT locaux
    access_token = create_access_token(
        subject=user.id,
        additional_claims={"role": user.role, "email": user.email},
    )
    refresh_token = create_refresh_token(subject=user.id)

    # Rediriger vers le frontend avec les tokens en query params
    # (le SAML flow est browser-based : l'IdP POST vers l'ACS,
    # donc on ne peut pas retourner du JSON au navigateur)
    frontend_url = getattr(settings, "FRONTEND_URL", "https://hellojadeapp.local")
    params = urlencode({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "saml": "1",
    })
    redirect_url = f"{frontend_url}/login?{params}"
    return RedirectResponse(url=redirect_url, status_code=302)


@router.post("/refresh", response_model=Token)
async def refresh_token(
    body: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Rafraîchir les tokens avec un refresh token
    """
    user_id = verify_token(body.refresh_token, token_type="refresh")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de rafraîchissement invalide",
        )

    from uuid import UUID
    user = await db.get(User, UUID(user_id))

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouvé",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte utilisateur désactivé",
        )

    new_access_token = create_access_token(
        subject=user.id,
        additional_claims={"role": user.role, "email": user.email},
    )
    new_refresh_token = create_refresh_token(subject=user.id)

    return Token(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
    )


@router.post("/logout")
async def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Déconnexion de l'utilisateur
    """
    await audit_service.log_action(
        db=db,
        action="logout",
        user_id=current_user.id,
        user_email=current_user.email,
        request=request,
    )

    return {"message": "Déconnexion réussie"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Récupérer les informations de l'utilisateur connecté
    """
    return UserResponse.from_orm_with_permissions(current_user)
