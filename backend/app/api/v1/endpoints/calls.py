"""
Endpoints pour la gestion des appels téléphoniques.

Initiation d'appels via Asterisk ARI + OVH SIP Trunk :
  POST /api/v1/calls/originate       → lancer un appel automatisé
  GET  /api/v1/calls/status/{cid}    → état Redis d'un appel en cours
  GET  /api/v1/calls/health          → état de l'API ARI Asterisk
"""
from typing import Any, List, Optional
from uuid import UUID
from datetime import datetime, timezone
import os

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user, get_pagination, PaginationParams
from app.models.call import Call
from app.models.patient import Patient
from app.models.user import User
from app.schemas.call import CallResponse, CallUpdate, CallWithAnalysis
from app.api.v1.endpoints.websocket import notify_call_status_update
from app.core.logging import get_logger
from app.services.telephony.asterisk_ari_service import asterisk_ari_service

logger = get_logger(__name__)

router = APIRouter()


# ── Schémas ──────────────────────────────────────────────────────────────────

class OriginateRequest(BaseModel):
    phone_number: Optional[str] = Field(default=None, description="Numéro du patient (format E.164 ou local belge) — si absent, utilise le téléphone du patient en base")
    patient_id: Optional[str] = Field(default=None, description="UUID du patient en base")
    notes: Optional[str] = Field(default=None, description="Notes libres pour cet appel")


class OriginateResponse(BaseModel):
    channel_id: str
    call_id: Optional[str]
    patient_id: Optional[str]
    phone_number: str
    status: str


# ── Initiation d'appel ───────────────────────────────────────────────────────

@router.post("/originate", response_model=OriginateResponse, status_code=status.HTTP_201_CREATED)
async def originate_call(
    req: OriginateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Initie un appel automatisé vers un patient via Asterisk ARI + OVH SIP.
    Crée un enregistrement Call en base puis déclenche l'appel.
    """
    if not asterisk_ari_service.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service Asterisk ARI non configuré (vérifier ASTERISK_ARI_* dans .env)",
        )

    # Créer l'entrée Call en DB avant de déclencher l'appel
    patient = None
    if req.patient_id:
        patient = await db.get(Patient, req.patient_id)
        if not patient:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient non trouvé")

    if not patient:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="patient_id requis pour initier un appel",
        )

    # Numéro cible : req.phone_number si fourni, sinon telephone du patient
    callee = req.phone_number or patient.telephone
    if not callee:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Numéro de téléphone du patient introuvable",
        )

    call = Call(
        patient_id=patient.id,
        caller_number=asterisk_ari_service.caller_number,
        callee_number=callee,
        status="pending",
        initiated_by=current_user.id,
        start_time=datetime.now(timezone.utc),
        call_metadata={"notes": req.notes, "provider": "asterisk_ari"},
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)

    # Déclencher l'appel Asterisk ARI
    channel_id = await asterisk_ari_service.originate(
        phone_number=callee,
        patient_id=str(patient.id),
        call_db_id=str(call.id),
    )

    if not channel_id:
        call.status = "failed"
        call.failure_reason = "Asterisk ARI originate a échoué"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Impossible d'initier l'appel via Asterisk ARI",
        )

    # Stocker le channel_id dans les métadonnées
    call.call_metadata = {**(call.call_metadata or {}), "channel_id": channel_id}
    call.asterisk_channel = channel_id
    await db.commit()

    await notify_call_status_update(str(call.id), "pending")

    logger.info(f"Appel initié: call_id={call.id} channel={channel_id} → {callee}")

    return OriginateResponse(
        channel_id=channel_id,
        call_id=str(call.id),
        patient_id=str(patient.id),
        phone_number=callee,
        status="pending",
    )


@router.get("/status/{channel_id}")
async def get_call_status(
    channel_id: str,
    current_user: User = Depends(get_current_user),
) -> Any:
    """État Redis en temps réel d'un appel en cours (par channel_id Asterisk)."""
    state = await asterisk_ari_service.get_call_status(channel_id)
    if not state:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appel non trouvé ou terminé")
    return state


@router.get("/health")
async def asterisk_health(current_user: User = Depends(get_current_user)) -> Any:
    """Vérifie la connectivité avec l'API ARI Asterisk."""
    ok = await asterisk_ari_service.health_check()
    return {
        "asterisk_ari": "up" if ok else "down",
        "configured": asterisk_ari_service.is_configured,
        "ari_url": asterisk_ari_service.base_url,
    }




# ── Board 3-colonnes ─────────────────────────────────────────────────────────

class BoardPatient(dict):
    pass


@router.get("/board")
async def get_calls_board(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Retourne le dernier appel par patient, classé en 3 colonnes :
    - alerts   : alerte clinique ou transfert échoué
    - ok       : appel complété sans alerte
    - unreachable : contact_failure (hors transfer_failed)
    """
    from sqlalchemy import func as sa_func, text as sa_text

    stmt = sa_text("""
        WITH ranked AS (
            SELECT
                c.id,
                c.patient_id,
                c.status,
                c.start_time,
                c.end_time,
                c.duration,
                c.failure_reason,
                c.metadata AS call_metadata,
                c.retry_count,
                c.max_retries,
                p.nom,
                p.prenom,
                p.telephone,
                p.next_call_scheduled,
                p.manually_recalled,
                a.risk_score,
                a.alerts AS analysis_alerts,
                a.summary AS analysis_summary,
                ROW_NUMBER() OVER (PARTITION BY c.patient_id ORDER BY c.created_at DESC) AS rn
            FROM calls c
            JOIN patients p ON c.patient_id = p.id
            LEFT JOIN analyses a ON a.call_id = c.id
        )
        SELECT * FROM ranked WHERE rn = 1
        ORDER BY start_time DESC NULLS LAST
    """)

    result = await db.execute(stmt)
    rows = result.mappings().all()

    alerts = []
    ok = []
    unreachable = []

    for r in rows:
        meta = r["call_metadata"] or {}
        alert_type = meta.get("alert_type")
        alert_reason = meta.get("alert_reason")
        alert_triggered = meta.get("alert_triggered", False)

        card = {
            "call_id": str(r["id"]),
            "patient_id": str(r["patient_id"]),
            "nom": r["nom"],
            "prenom": r["prenom"],
            "telephone": r["telephone"],
            "status": r["status"],
            "start_time": r["start_time"].isoformat() if r["start_time"] else None,
            "end_time": r["end_time"].isoformat() if r["end_time"] else None,
            "duration": r["duration"],
            "alert_type": alert_type,
            "alert_reason": alert_reason,
            "risk_score": r["risk_score"],
            "analysis_summary": r["analysis_summary"],
            "next_call_scheduled": r["next_call_scheduled"].isoformat() if r["next_call_scheduled"] else None,
            "manually_recalled": r["manually_recalled"],
        }

        is_transfer_failed = (
            alert_type == "contact_failure" and alert_reason == "transfer_failed"
        )
        is_clinical = alert_type == "clinical"

        if is_clinical or is_transfer_failed:
            card["transfer_ok"] = not is_transfer_failed
            alerts.append(card)
        elif r["status"] == "completed" and not alert_triggered:
            ok.append(card)
        else:
            card["retry_pending"] = r["next_call_scheduled"] is not None
            unreachable.append(card)

    return {"alerts": alerts, "ok": ok, "unreachable": unreachable}

@router.get("", response_model=List[CallWithAnalysis])
async def get_calls(
    patient_id: Optional[UUID] = None,
    status_filter: Optional[str] = None,
    alert_type: Optional[str] = None,
    pagination: PaginationParams = Depends(get_pagination),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Récupérer la liste des appels"""

    stmt = select(Call).options(
        selectinload(Call.patient),
        selectinload(Call.transcription),
        selectinload(Call.analysis)
    )

    if patient_id:
        stmt = stmt.where(Call.patient_id == patient_id)

    if status_filter:
        stmt = stmt.where(Call.status == status_filter)

    if alert_type:
        stmt = stmt.where(text("calls.metadata->>'alert_type' = :alert_type").bindparams(alert_type=alert_type))

    stmt = stmt.order_by(Call.created_at.desc())
    stmt = stmt.offset(pagination.skip).limit(pagination.limit)

    result = await db.execute(stmt)
    calls = result.scalars().all()

    for call in calls:
        _ = call.id, call.status, call.created_at, call.updated_at, call.duration, call.start_time, call.end_time

    return [CallWithAnalysis.model_validate(call) for call in calls]


@router.get("/{call_id}", response_model=CallWithAnalysis)
async def get_call(
    call_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Récupérer un appel par son ID avec transcription et analyse"""

    stmt = select(Call).options(
        selectinload(Call.patient),
        selectinload(Call.transcription),
        selectinload(Call.analysis)
    ).where(Call.id == call_id)

    result = await db.execute(stmt)
    call = result.scalar_one_or_none()

    if not call:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appel non trouvé",
        )

    return CallWithAnalysis.model_validate(call)


@router.patch("/{call_id}", response_model=CallResponse)
async def update_call(
    call_id: UUID,
    call_update: CallUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Mettre à jour un appel"""

    call = await db.get(Call, call_id)

    if not call:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appel non trouvé",
        )

    old_status = call.status
    update_data = call_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(call, field, value)

    await db.commit()
    await db.refresh(call)

    if 'status' in update_data and old_status != call.status:
        await notify_call_status_update(str(call.id), call.status)

    return CallResponse.model_validate(call)


@router.get("/{call_id}/recording")
async def get_call_recording(
    call_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Télécharger l'enregistrement audio complet d'un appel."""
    result = await db.execute(
        select(Call).options(selectinload(Call.patient)).where(Call.id == call_id)
    )
    call = result.scalar_one_or_none()

    if not call:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appel non trouvé")

    if not call.recording_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Aucun enregistrement pour cet appel")

    if not os.path.exists(call.recording_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fichier audio introuvable")

    patient_name = ""
    if call.patient:
        prenom = getattr(call.patient, 'prenom', None) or getattr(call.patient, 'first_name', None) or ''
        nom = getattr(call.patient, 'nom', None) or getattr(call.patient, 'last_name', None) or ''
        patient_name = f"_{prenom}_{nom}".strip("_").strip("_")
    filename = f"appel{patient_name}_{call_id}.wav"

    return FileResponse(
        path=call.recording_path,
        media_type="audio/wav",
        filename=filename,
    )


@router.delete("/{call_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_call(
    call_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Supprimer un appel et toutes ses données associées (transcription, analyse)"""

    call = await db.get(Call, call_id)

    if not call:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appel non trouvé",
        )

    if call.recording_path and os.path.exists(call.recording_path):
        try:
            os.unlink(call.recording_path)
            logger.info(f"Fichier d'enregistrement supprimé: {call.recording_path}")
        except Exception as e:
            logger.warning(f"Erreur lors de la suppression du fichier d'enregistrement: {e}")

    await db.delete(call)
    await db.commit()

    logger.info(f"Appel {call_id} supprimé avec succès")

    return None


@router.post("/{call_id}/status")
async def update_call_status(
    call_id: UUID,
    status_data: dict,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Mettre à jour le statut d'un appel"""
    call = await db.get(Call, call_id)
    if not call:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appel non trouvé")

    old_status = call.status
    new_status = status_data.get("status")
    failure_reason = status_data.get("reason") or status_data.get("error")

    if new_status:
        call.status = new_status

    if failure_reason:
        call.failure_reason = failure_reason

    if new_status == "in_progress" and not call.start_time:
        call.start_time = datetime.now()
    elif new_status == "completed" and not call.end_time:
        call.end_time = datetime.now()
        if call.start_time:
            duration = (call.end_time - call.start_time).total_seconds()
            call.duration = int(duration)

    await db.commit()
    await db.refresh(call)

    await notify_call_status_update(str(call.id), call.status)

    return {"status": "updated", "call_id": str(call.id)}
