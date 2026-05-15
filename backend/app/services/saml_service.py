"""
Service d'intégration SAML2 / Intra ID pour Epicura.

Objectifs :
- Centraliser la configuration OneLogin python3-saml à partir de app.core.config.settings
- Offrir des helpers pour :
  - construire une requête SAML à partir d'une Request FastAPI
  - lancer un login SAML (URL de redirection)
  - traiter l'assertion SAML reçue (ACS) et en extraire les informations utiles
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from starlette.requests import Request
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.settings import OneLogin_Saml2_Settings

from app.core.config import settings


def _require_saml_enabled() -> None:
    """Vérifie que SAML2 est activé dans la configuration."""
    if not settings.SAML2_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentification SAML2 désactivée dans la configuration.",
        )


def _build_saml_settings() -> OneLogin_Saml2_Settings:
    """
    Construit la configuration OneLogin à partir des settings.

    Remarque :
    - La plupart des valeurs sont injectées via les variables d'environnement SAML2_*
    - Les URLs exactes (entityID, ACS, SLO) doivent être fournies par la configuration Epicura.
    """
    sp_entity_id = settings.SAML2_SP_ENTITY_ID
    acs_url = settings.SAML2_SP_ASSERTION_CONSUMER_SERVICE_URL
    slo_url = settings.SAML2_SP_SINGLE_LOGOUT_SERVICE_URL

    idp_entity_id = settings.SAML2_IDP_ENTITY_ID
    idp_sso_url = settings.SAML2_IDP_SSO_URL
    idp_slo_url = settings.SAML2_IDP_SLO_URL
    idp_cert = settings.SAML2_IDP_X509_CERT

    if not all([sp_entity_id, acs_url, idp_entity_id, idp_sso_url, idp_cert]):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration SAML2 incomplète. Vérifiez les variables SAML2_* dans .env.",
        )

    saml_settings: Dict[str, Any] = {
        "strict": False,
        "debug": settings.DEBUG,
        "sp": {
            "entityId": sp_entity_id,
            "assertionConsumerService": {
                "url": acs_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "singleLogoutService": {
                "url": slo_url or "",
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "NameIDFormat": settings.SAML2_NAMEID_FORMAT,
        },
        "idp": {
            "entityId": idp_entity_id,
            "singleSignOnService": {
                "url": idp_sso_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "singleLogoutService": {
                "url": idp_slo_url or "",
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": idp_cert,
        },
    }

    return OneLogin_Saml2_Settings(settings=saml_settings)


async def _prepare_fastapi_request(request: Request) -> Dict[str, Any]:
    """
    Adapte une Request FastAPI au format attendu par python3-saml.

    Voir la doc OneLogin pour le format attendu.
    """
    url = request.url
    host = request.headers.get("host", url.hostname or "localhost")

    # GET params
    get_data = dict(request.query_params)

    # POST params (uniquement pour l'ACS)
    if request.method.upper() == "POST":
        form = await request.form()
        post_data = dict(form)
    else:
        post_data = {}

    # Derrière nginx, utiliser X-Forwarded-Proto pour le schéma réel
    forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
    if forwarded_proto == "https":
        is_https = True
    else:
        is_https = url.scheme == "https"
    port = url.port or (443 if is_https else 80)

    return {
        "https": "on" if is_https else "off",
        "http_host": host,
        "server_port": str(port),
        "script_name": url.path,
        "path_info": url.path,
        "get_data": get_data,
        "post_data": post_data,
    }


async def build_saml_auth(request: Request) -> OneLogin_Saml2_Auth:
    """Construit un objet OneLogin_Saml2_Auth à partir de la requête FastAPI."""
    _require_saml_enabled()
    saml_req = await _prepare_fastapi_request(request)
    saml_settings = _build_saml_settings()
    return OneLogin_Saml2_Auth(saml_req, old_settings=saml_settings)


def map_groups_to_role(groups: List[str]) -> str:
    """
    Mappe les groupes AD/IntraID vers un rôle HelloJADE.

    Priorité : admin > medecin > infirmier > operateur.
    Les noms de groupes sont normalisés (Keycloak préfixe avec /).
    """
    normalized = [g.strip("/").upper() for g in groups if g]

    admin_groups = [g.upper() for g in settings.SAML2_ADMIN_GROUPS]

    for g in normalized:
        if g in admin_groups or "ADMIN" in g:
            return "admin"

    for g in normalized:
        if "MEDECIN" in g:
            return "medecin"

    for g in normalized:
        if "INFIRMIER" in g:
            return "infirmier"

    for g in normalized:
        if "OPERATEUR" in g:
            return "operateur"

    # Rôle par défaut si aucun groupe reconnu
    return "operateur"


def extract_user_info_from_auth(auth: OneLogin_Saml2_Auth) -> Dict[str, Any]:
    """
    Extrait les informations utilisateur pertinentes de l'assertion SAML.

    Retourne typiquement :
    {
        "name_id": "...",
        "email": "...",
        "full_name": "...",
        "groups": [...],
    }
    """
    attributes = auth.get_attributes()

    # Ces clés exactes dépendront de la configuration Epicura (à affiner avec eux)
    email = auth.get_nameid() or attributes.get("Email", [None])[0]
    full_name = attributes.get("FullName", [None])[0] or attributes.get(
        "displayName", [None]
    )[0]

    groups_attr = settings.SAML2_GROUP_ATTRIBUTE
    groups: List[str] = attributes.get(groups_attr, [])  # type: ignore[assignment]

    return {
        "name_id": auth.get_nameid(),
        "email": email,
        "full_name": full_name,
        "groups": groups,
        "attributes": attributes,
    }

