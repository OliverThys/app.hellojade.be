"""
Endpoints pour les analytics prédictifs et les tendances
"""
from typing import Any, Dict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.patient import Patient
from app.models.user import User
from app.services.predictive_analytics_service import predictive_analytics_service

router = APIRouter()


@router.get("/patients/{patient_id}/trends")
async def get_patient_trends(
    patient_id: UUID,
    days: int = Query(30, ge=7, le=90),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Récupère les tendances d'évolution d'un patient
    
    Calcule les tendances sur les indicateurs clés :
    - Score de risque
    - Niveau de douleur
    - Compliance médicamenteuse
    - État moral
    """
    # Vérifier que le patient existe
    patient = await db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient non trouvé",
        )
    
    trends = await predictive_analytics_service.calculate_patient_trends(
        db=db,
        patient_id=patient_id,
        days=days,
    )
    
    return trends


@router.get("/patients/{patient_id}/early-warnings")
async def get_early_warnings(
    patient_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Détecte les signaux d'alerte précoce pour un patient
    
    Identifie les signaux de dégradation avant qu'ils ne deviennent critiques.
    """
    # Vérifier que le patient existe
    patient = await db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient non trouvé",
        )
    
    signals = await predictive_analytics_service.detect_early_warning_signals(
        db=db,
        patient_id=patient_id,
    )
    
    return {
        "patient_id": str(patient_id),
        "patient_name": f"{patient.prenom} {patient.nom}",
        "signals": signals,
        "signals_count": len(signals),
        "has_urgent_signals": any(s.get("severity") == "urgent" for s in signals),
    }


@router.get("/patients/{patient_id}/readmission-risk")
async def get_readmission_risk(
    patient_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Prédit le risque de réadmission hospitalière
    
    Analyse les facteurs de risque et calcule une probabilité de réadmission.
    """
    # Vérifier que le patient existe
    patient = await db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient non trouvé",
        )
    
    prediction = await predictive_analytics_service.predict_readmission_risk(
        db=db,
        patient_id=patient_id,
    )
    
    return prediction


@router.get("/patients/{patient_id}/evolution-timeline")
async def get_evolution_timeline(
    patient_id: UUID,
    days: int = Query(30, ge=7, le=90),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Génère une timeline de l'évolution du patient
    
    Retourne les points de données pour visualiser l'évolution dans le temps.
    """
    # Vérifier que le patient existe
    patient = await db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient non trouvé",
        )
    
    timeline = await predictive_analytics_service.get_patient_evolution_timeline(
        db=db,
        patient_id=patient_id,
        days=days,
    )
    
    return {
        "patient_id": str(patient_id),
        "patient_name": f"{patient.prenom} {patient.nom}",
        "timeline": timeline,
        "data_points": len(timeline),
        "days_analyzed": days,
    }


@router.get("/patients/{patient_id}/cohort-comparison")
async def get_cohort_comparison(
    patient_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Compare un patient avec une cohorte de patients similaires
    
    Permet de voir si le patient évolue mieux ou moins bien que la moyenne.
    """
    # Vérifier que le patient existe
    patient = await db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient non trouvé",
        )
    
    comparison = await predictive_analytics_service.get_cohort_comparison(
        db=db,
        patient_id=patient_id,
    )
    
    return comparison

