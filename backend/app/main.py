"""
Point d'entrée principal de l'application FastAPI HelloJADE
"""
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.middleware.sessions import SessionMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.logging import setup_logging
from app.database import init_db
from app.middleware.rate_limiter import RateLimitMiddleware


# Configuration du logging
logger = setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Gestion du cycle de vie de l'application"""
    # Startup
    logger.info(f"Démarrage de HelloJADE v{settings.VERSION}")
    logger.info(f"Environnement: {settings.ENVIRONMENT}")
    
    # Initialiser la base de données
    await init_db()

    # Enregistrer le snapshot d'usine du questionnaire (une seule fois)
    from app.database import AsyncSessionLocal
    from app.api.v1.endpoints.admin import seed_factory_default_if_needed
    async with AsyncSessionLocal() as db:
        await seed_factory_default_if_needed(db)

    # Démarrer le listener WebSocket Asterisk ARI
    from app.services.telephony.asterisk_ari_service import asterisk_ari_service
    asterisk_ari_service.start_ws_listener()

    yield
    
    # Shutdown
    logger.info("Arrêt de HelloJADE")


# Créer l'application FastAPI
app = FastAPI(
    title=settings.APP_NAME,
    description="API Backend pour HelloJADE - Système de suivi post-hospitalisation avec IA",
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json" if settings.DEBUG else None,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)


# Rate limiting middleware (avant CORS pour intercepter toutes les requêtes)
if settings.RATE_LIMIT_ENABLED:
    app.add_middleware(
        RateLimitMiddleware,
        enabled=settings.RATE_LIMIT_ENABLED,
    )

# Configuration CORS
# En développement, autoriser toutes les origines (y compris depuis d'autres PC du réseau)
# En production, autoriser HTTPS + origines Tauri (tauri://localhost, http://tauri.localhost)
if settings.ENVIRONMENT != "production":
    # En développement : autoriser toutes les origines pour les tests réseau
    cors_origins = ["*"]
else:
    # En production: autoriser HTTPS et les origines Tauri
    cors_origins = [
        origin for origin in settings.CORS_ORIGINS
        if origin.startswith("https://") or origin.startswith("tauri://") or origin.startswith("http://tauri")
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)


# Middleware de sécurité
# En développement, désactiver TrustedHostMiddleware pour autoriser l'accès depuis tous les hôtes du réseau
if settings.ENVIRONMENT == "production":
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.TRUSTED_HOSTS,
    )


# Middleware de session
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    session_cookie="hellojadeapp-session",
    max_age=settings.SESSION_EXPIRE_MINUTES * 60,
    same_site="lax",
    https_only=settings.ENVIRONMENT == "production",
)


# Instrumentation Prometheus
if settings.PROMETHEUS_ENABLED:
    instrumentator = Instrumentator(
        excluded_handlers=["/metrics", "/health", "/docs", "/openapi.json", "/redoc"],
    )
    instrumentator.instrument(app).expose(app, endpoint="/metrics")
    
    # Enregistrer les métriques personnalisées
    from app.core.metrics import CUSTOM_REGISTRY
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST, REGISTRY
    from fastapi.responses import Response
    
    # Ajouter les métriques personnalisées au registre par défaut pour qu'elles soient sur /metrics
    for collector in CUSTOM_REGISTRY._collector_to_names:
        REGISTRY.register(collector)
    
    @app.get("/metrics/custom")
    async def custom_metrics():
        """Endpoint pour les métriques personnalisées (dédié)"""
        return Response(
            content=generate_latest(CUSTOM_REGISTRY),
            media_type=CONTENT_TYPE_LATEST
        )


# Gestionnaire d'exceptions global
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Gestionnaire global des exceptions non gérées"""
    logger.error(f"Exception non gérée: {str(exc)}", exc_info=True)
    
    if settings.DEBUG:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "Erreur interne du serveur",
                "error": str(exc),
                "type": type(exc).__name__,
            },
        )
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Erreur interne du serveur"},
    )


# Routes racine
@app.get("/", tags=["Root"])
async def root() -> dict[str, Any]:
    """Route racine de l'API"""
    return {
        "name": settings.APP_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "status": "operational",
        "docs": "/docs" if settings.DEBUG else None,
    }


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, Any]:
    """Endpoint de health check"""
    return {
        "status": "healthy",
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
    }


@app.get("/ready", tags=["Health"])
async def readiness_check() -> dict[str, Any]:
    """Endpoint de readiness check"""
    # TODO: Vérifier les connexions DB, Redis, etc.
    return {
        "status": "ready",
        "database": "connected",
        "redis": "connected",
        "asterisk": "connected",
    }


# Inclure les routes API
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
    )

