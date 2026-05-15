"""
Router pour l'API v1
"""
from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin,
    analytics,
    auth,
    calls,
    dashboard,
    documents,
    hl7_receiver,
    patients,
    reports,
    websocket,
)
from app.core.config import settings

# Router pour l'API v1
api_router = APIRouter()

api_router.include_router(admin.router, prefix="/admin", tags=["Administration"])
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(patients.router, prefix="/patients", tags=["Patients"])
api_router.include_router(calls.router, prefix="/calls", tags=["Calls"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
api_router.include_router(reports.router, prefix="/reports", tags=["Reports"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
api_router.include_router(websocket.router, prefix="/ws", tags=["WebSocket"])
api_router.include_router(documents.router, prefix="/documents", tags=["Documents"])
api_router.include_router(hl7_receiver.router, tags=["HL7 Integration"])

if settings.SIMULATION_MODE:
    from app.api.v1.endpoints import simulation as sim_endpoints
    api_router.include_router(sim_endpoints.router, tags=["Simulation E2E"])
