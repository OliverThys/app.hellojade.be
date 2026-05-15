"""
Endpoints pour les rapports PDF
"""
from typing import Any, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.report import Report
from app.models.call import Call
from app.models.user import User
from app.schemas.report import ReportCreate, ReportResponse
from app.services.report_service import report_service
from app.services.hl7_epicura_service import epicura_hl7_service

router = APIRouter()


@router.get("/stats")
async def get_report_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Récupérer les statistiques des rapports pour les graphiques"""

    if not current_user.can_view_reports:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions insuffisantes",
        )

    from sqlalchemy import func, case
    from datetime import datetime, timedelta
    from app.models.analysis import Analysis

    # Stats générales
    total_reports = await db.scalar(select(func.count(Report.id)))

    # Stats par type de rapport
    type_stats = await db.execute(
        select(Report.report_type, func.count(Report.id))
        .group_by(Report.report_type)
    )
    reports_by_type = {row[0]: row[1] for row in type_stats.fetchall()}

    # Stats par niveau de risque (via Analysis)
    risk_stats = await db.execute(
        select(
            case(
                (Analysis.risk_score < 4, "low"),
                (Analysis.risk_score.between(4, 6), "medium"),
                (Analysis.risk_score.between(7, 8), "high"),
                (Analysis.risk_score >= 9, "critical"),
                else_="unknown"
            ).label("risk_level"),
            func.count(Report.id)
        )
        .select_from(Report)
        .join(Analysis, Report.analysis_id == Analysis.id)
        .group_by("risk_level")
    )
    reports_by_risk = {row[0]: row[1] for row in risk_stats.fetchall()}

    # Évolution sur les 30 derniers jours
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    evolution_data = await db.execute(
        select(
            func.date(Report.created_at).label("date"),
            func.count(Report.id).label("count")
        )
        .where(Report.created_at >= thirty_days_ago)
        .group_by("date")
        .order_by("date")
    )
    reports_evolution = [
        {"date": row[0].isoformat(), "count": row[1]}
        for row in evolution_data.fetchall()
    ]

    # Rapports générés vs envoyés
    generated_count = await db.scalar(
        select(func.count(Report.id)).where(Report.status == "generated")
    )
    sent_count = await db.scalar(
        select(func.count(Report.id)).where(Report.status == "sent")
    )

    return {
        "total_reports": total_reports or 0,
        "reports_by_type": reports_by_type,
        "reports_by_risk": reports_by_risk,
        "reports_evolution": reports_evolution,
        "generated_count": generated_count or 0,
        "sent_count": sent_count or 0,
    }


@router.get("", response_model=List[ReportResponse])
async def get_reports(
    call_id: UUID = None,
    risk_level: str = None,
    report_type: str = None,
    start_date: str = None,
    end_date: str = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Récupérer la liste des rapports avec filtres avancés"""

    if not current_user.can_view_reports:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions insuffisantes",
        )

    from sqlalchemy.orm import selectinload
    from datetime import datetime
    from app.models.analysis import Analysis

    # Joindre les relations
    stmt = (
        select(Report)
        .options(
            selectinload(Report.call).selectinload(Call.patient),
            selectinload(Report.analysis),
            selectinload(Report.generated_by_user)
        )
        .order_by(Report.created_at.desc())
    )

    if call_id:
        stmt = stmt.where(Report.call_id == call_id)

    if report_type:
        stmt = stmt.where(Report.report_type == report_type)

    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            stmt = stmt.where(Report.created_at >= start_dt)
        except ValueError:
            pass

    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            stmt = stmt.where(Report.created_at <= end_dt)
        except ValueError:
            pass

    # Filtrer par risk_level via l'analyse
    if risk_level:
        stmt = stmt.join(Analysis, Report.analysis_id == Analysis.id)
        if risk_level == "low":
            stmt = stmt.where(Analysis.risk_score < 4)
        elif risk_level == "medium":
            stmt = stmt.where(Analysis.risk_score.between(4, 6))
        elif risk_level == "high":
            stmt = stmt.where(Analysis.risk_score.between(7, 8))
        elif risk_level == "critical":
            stmt = stmt.where(Analysis.risk_score >= 9)

    result = await db.execute(stmt)
    reports = result.scalars().all()

    return [ReportResponse.model_validate(report) for report in reports]


@router.get("/by-call/{call_id}")
async def get_report_by_call(
    call_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Retourne le rapport PDF ORU d'un appel (id + status + filename), ou métadonnées vides si absent."""
    stmt = (
        select(Report)
        .where(Report.call_id == call_id)
        .order_by(Report.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    report = result.scalar_one_or_none()
    from pathlib import Path

    # 200 + métadonnées « vides » : évite un 404 bruité dans le navigateur quand le PDF ORU
    # n'existe pas encore (le front traite l'absence via !id).
    if not report:
        return {
            "id": None,
            "status": "none",
            "filename": None,
            "file_exists": False,
            "created_at": None,
        }
    return {
        "id": str(report.id),
        "status": report.status,
        "filename": report.filename or f"rapport_{report.id}.pdf",
        "file_exists": Path(report.file_path).exists() if report.file_path else False,
        "created_at": report.created_at.isoformat(),
    }


@router.get("/{report_id}/download")
async def download_report(
    report_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Télécharger un rapport PDF"""
    
    if not current_user.can_view_reports:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions insuffisantes",
        )
    
    report = await db.get(Report, report_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rapport non trouvé",
        )
    
    # Vérifier que le fichier existe
    from pathlib import Path
    file_path = Path(report.file_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Le fichier PDF n'existe pas",
        )
    
    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        filename=report.filename or f"rapport_{report_id}.pdf",
        headers={"Content-Disposition": f'attachment; filename="{report.filename or f"rapport_{report_id}.pdf"}"'},
    )


@router.post("/generate/{call_id}")
async def generate_report(
    call_id: UUID,
    report_type: str = "standard",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Générer un rapport PDF pour un appel"""
    
    if not current_user.can_view_reports:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions insuffisantes",
        )
    
    # Récupérer l'appel avec toutes ses relations
    call = await db.get(Call, call_id)
    if not call:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appel non trouvé",
        )
    
    # Charger les relations
    await db.refresh(call, ["patient", "transcription", "analysis"])
    
    # Préparer les données
    call_data = {
        "id": str(call.id),
        "created_at": call.created_at.isoformat() if call.created_at else None,
        "duration": call.duration,
        "status": call.status,
    }
    
    patient_data = {
        "nom": call.patient.nom,
        "prenom": call.patient.prenom,
        "numero_dossier": call.patient.numero_dossier,
        "telephone": call.patient.telephone,
        "service_hospitalisation": call.patient.service_hospitalisation,
        "diagnostic_principal": call.patient.diagnostic_principal,
    }
    
    transcription_data = None
    if call.transcription:
        raw_segments = call.transcription.segments
        # Normaliser: segments peut être une liste ou un dict {"segments": [...]}
        if isinstance(raw_segments, dict):
            segments_list = raw_segments.get("segments") or []
        elif isinstance(raw_segments, list):
            segments_list = raw_segments
        else:
            segments_list = []
        transcription_data = {
            "full_text": call.transcription.full_text,
            "language": call.transcription.language,
            "confidence": call.transcription.confidence,
            "segments": segments_list or None,
        }

    analysis_data = None
    if call.analysis:
        a = call.analysis
        analysis_data = {
            # Nouveaux champs
            "has_pain": a.has_pain,
            "pain_level": a.pain_level,
            "pain_relieved": a.pain_relieved,
            "eating_normally": a.eating_normally,
            "eating_difficulty_score": a.eating_difficulty_score,
            "has_nausea": a.has_nausea,
            "blood_in_vomit": a.blood_in_vomit,
            "has_headache": a.has_headache,
            "headache_level": a.headache_level,
            "has_bleeding": a.has_bleeding,
            "bleeding_stopped": a.bleeding_stopped,
            "infection_signs": a.infection_signs,
            "contacted_emergency": a.contacted_emergency,
            "emergency_reason": a.emergency_reason,
            "understands_instructions": a.understands_instructions,
            "instruction_doubts": a.instruction_doubts,
            # Champs legacy
            "pain_location": a.pain_location,
            "pain_description": a.pain_description,
            "has_fever": a.has_fever,
            "fever_temperature": a.fever_temperature,
            "fever_duration": a.fever_duration,
            "takes_medication": a.takes_medication,
            "medication_regularity": a.medication_regularity,
            "medication_issues": a.medication_issues,
            "moral_state": a.moral_state,
            "moral_description": a.moral_description,
            "summary": a.summary,
            "alerts": a.alerts,
            "recommendations": a.recommendations,
            "risk_score": a.risk_score,
        }
    
    raw_meta = getattr(call, "call_metadata", None)
    call_meta = raw_meta if isinstance(raw_meta, dict) else None

    # Générer le PDF
    pdf_path = report_service.generate_call_report(
        call_data=call_data,
        patient_data=patient_data,
        transcription_data=transcription_data,
        analysis_data=analysis_data,
        call_metadata=call_meta,
        report_type=report_type,
    )

    # Générer le message HL7 ORU^R01 pour Epicura (PDF encapsulé en base64)
    hl7_path = None
    hl7_sent = False
    try:
        # Enrichir patient_data avec séjour/visite si disponibles
        if hasattr(call.patient, "sejour_id") and call.patient.sejour_id:
            patient_data["sejour_id"] = call.patient.sejour_id
        if hasattr(call.patient, "visite_id") and call.patient.visite_id:
            patient_data["visite_id"] = call.patient.visite_id

        hl7_path = epicura_hl7_service.generate_oru_message(
            call_data=call_data,
            patient_data=patient_data,
            pdf_path=pdf_path,
        )
        # Envoyer vers Mirth
        send_result = await epicura_hl7_service.send_oru(hl7_path)
        hl7_sent = send_result.get("success", False)
    except Exception as e:
        from app.core.logging import get_logger
        _logger = get_logger(__name__)
        _logger.error(f"Erreur lors de la génération/envoi HL7 ORU: {e}")

    # Créer l'enregistrement du rapport
    import os
    file_size = os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 0

    report = Report(
        call_id=call.id,
        analysis_id=call.analysis.id if call.analysis else None,
        generated_by=current_user.id,
        report_type=report_type,
        file_path=pdf_path,
        file_size=file_size,
        status="sent" if hl7_sent else "generated",
    )

    db.add(report)
    await db.commit()
    await db.refresh(report)

    return ReportResponse.model_validate(report)

