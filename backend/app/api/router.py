"""
Router principal de l'API
"""
from fastapi import APIRouter

from app.api.v1.router import api_router as v1_router

# Router principal de l'API
api_router = APIRouter()

# Inclure les routes v1
# Note: Le préfixe /api/v1 est ajouté dans main.py via API_V1_PREFIX
api_router.include_router(
    v1_router,
    tags=["v1"],
)

