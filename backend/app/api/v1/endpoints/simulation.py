"""
Endpoints de simulation E2E — HelloJADE Epicura

Ce module expose des routes utilitaires UNIQUEMENT quand SIMULATION_MODE=true.
Il ne doit JAMAIS être enregistré en production.

Route principale :
  POST /sim/inject-call
    Crée un appel synthétique complet (Call + Transcription + Analysis)
    directement en base, puis génère le rapport PDF et envoie l'ORU HL7.
    Permet de tester la chaîne complète sans Asterisk ni patient réel.

Auth : API key partagée (X-HL7-API-Key) — même clé que l'intégration Mirth.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.database import get_db
from app.models.analysis import Analysis
from app.models.call import Call
from app.models.patient import Patient
from app.models.report import Report
from app.models.transcription import Transcription
from app.services.hl7_epicura_service import epicura_hl7_service
from app.services.report_service import report_service

logger = get_logger(__name__)

router = APIRouter(prefix="/sim", tags=["Simulation"])


# ---------------------------------------------------------------------------
# Auth (API key identique à l'intégration Mirth pour simplifier)
# ---------------------------------------------------------------------------


async def _require_sim_key(
    x_hl7_api_key: str = Header(..., alias="X-HL7-API-Key"),
) -> str:
    if not settings.HL7_API_KEY or x_hl7_api_key != settings.HL7_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Clé API de simulation invalide",
        )
    return x_hl7_api_key


# ---------------------------------------------------------------------------
# Données synthétiques par défaut
# ---------------------------------------------------------------------------

_DEFAULT_TRANSCRIPT = (
    "Bonjour, ici le service de suivi post-hospitalisation de l'hôpital Epicura. "
    "Comment vous sentez-vous depuis votre sortie ?\n"
    "Patient : Ça va plutôt bien, j'ai encore un peu mal mais c'est supportable.\n"
    "Avez-vous de la fièvre ?\n"
    "Patient : Non, pas de fièvre. J'ai pris mon thermomètre ce matin, 36.8.\n"
    "Prenez-vous bien vos médicaments ?\n"
    "Patient : Oui, exactement comme prescrit, matin et soir.\n"
    "Y a-t-il des saignements au niveau de la plaie ?\n"
    "Patient : Non, la plaie est propre, le pansement est intact.\n"
    "Mangez-vous normalement ?\n"
    "Patient : Oui, j'ai bon appétit depuis hier soir.\n"
    "Très bien. Si vous ressentez une aggravation, n'hésitez pas à appeler le 15. "
    "Bonne journée !"
)

_DEFAULT_ANALYSIS: Dict[str, Any] = {
    "has_pain": True,
    "pain_level": 3,
    "pain_relieved": True,
    "eating_normally": True,
    "eating_difficulty_score": 1,
    "drinking_possible": True,
    "has_nausea": False,
    "has_headache": False,
    "has_bleeding": False,
    "infection_signs": False,
    "contacted_emergency": False,
    "understands_instructions": True,
    "has_fever": False,
    "takes_medication": True,
    "medication_regularity": "toujours",
    "moral_state": 4,
    "summary": (
        "Patient en bonne voie de récupération. Douleur légère (3/10) bien contrôlée "
        "par les antalgiques. Pas de fièvre, pas de complications. Compliance "
        "médicamenteuse excellente. Alimentation normale rétablie."
    ),
    "alerts": [],
    "recommendations": [
        "Continuer les antalgiques selon prescription.",
        "Surveiller la plaie (rougeur, suintement) pendant encore 48h.",
        "Reprendre le suivi médical si douleur > 6/10.",
    ],
    "risk_score": 2,
    "model_used": "simulation",
    "confidence": 1.0,
}


# ---------------------------------------------------------------------------
# Endpoint principal
# ---------------------------------------------------------------------------


@router.post("/inject-call")
async def inject_call(
    payload: Optional[Dict[str, Any]] = None,
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(_require_sim_key),
) -> Any:
    """
    Injecte un appel simulé complet dans la base et déclenche la chaîne
    rapport → ORU → Mirth.

    Body JSON optionnel :
    {
        "numero_dossier": "SIM-2024-001",   // doit exister en base (créé par ADT)
        "transcription": "...",             // texte libre
        "risk_score": 2,
        "pain_level": 3,
        "caller_number": "+3227000000",
        "duration": 180
    }

    Retourne :
    {
        "call_id": "...",
        "patient_id": "...",
        "report_id": "...",
        "hl7_sent": true|false,
        "pdf_path": "...",
        "hl7_path": "..."
    }
    """
    if payload is None:
        payload = {}

    numero_dossier: str = payload.get("numero_dossier", "")

    # ------------------------------------------------------------------
    # 1. Trouver le patient (doit avoir été créé par l'ADT A03)
    # ------------------------------------------------------------------
    patient: Optional[Patient] = None
    if numero_dossier:
        result = await db.execute(
            select(Patient).where(Patient.numero_dossier == numero_dossier)
        )
        patient = result.scalar_one_or_none()

    if patient is None:
        # Fallback : prendre le dernier patient créé via HL7
        result = await db.execute(
            select(Patient)
            .where(Patient.hl7_source == "ADT_MIRTH")
            .order_by(Patient.created_at.desc())
            .limit(1)
        )
        patient = result.scalar_one_or_none()

    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Aucun patient trouvé. Envoyez d'abord un ADT A03 via "
                "POST mirth-mock:8099/trigger-adt"
            ),
        )

    logger.info(
        f"[SIM] Injection appel pour patient {patient.numero_dossier} ({patient.nom} {patient.prenom})"
    )

    # ------------------------------------------------------------------
    # 2. Créer le Call simulé
    # ------------------------------------------------------------------
    now = datetime.now(timezone.utc)
    duration_s: int = int(payload.get("duration", 180))
    caller_number: str = payload.get("caller_number", settings.ASTERISK_CALLER_NUMBER or "+3227000000")

    call = Call(
        id=uuid4(),
        patient_id=patient.id,
        asterisk_call_id=f"sim-{uuid4().hex[:8]}",
        caller_number=caller_number,
        callee_number=patient.telephone or "+3247000000",
        status="completed",
        start_time=now,
        answer_time=now,
        end_time=now,
        duration=duration_s,
        call_metadata={"simulation": True, "injected_at": now.isoformat()},
    )
    db.add(call)
    await db.flush()  # Obtenir call.id sans commit

    # ------------------------------------------------------------------
    # 3. Créer la Transcription synthétique
    # ------------------------------------------------------------------
    transcript_text: str = payload.get("transcription", _DEFAULT_TRANSCRIPT)

    transcription = Transcription(
        id=uuid4(),
        call_id=call.id,
        full_text=transcript_text,
        language="fr-BE",
        whisper_model="simulation",
        confidence=1.0,
        processing_time=0.0,
        segments={"simulation": True, "segments": []},
    )
    db.add(transcription)
    await db.flush()

    # ------------------------------------------------------------------
    # 4. Créer l'Analysis synthétique
    # ------------------------------------------------------------------
    analysis_overrides: Dict[str, Any] = {
        k: v
        for k, v in payload.items()
        if k in _DEFAULT_ANALYSIS and k not in ("numero_dossier", "transcription", "duration", "caller_number")
    }
    analysis_data = {**_DEFAULT_ANALYSIS, **analysis_overrides}

    analysis = Analysis(
        id=uuid4(),
        call_id=call.id,
        transcription_id=transcription.id,
        **{k: v for k, v in analysis_data.items() if k not in ("model_used", "confidence")},
        model_used=analysis_data.get("model_used", "simulation"),
        confidence=float(analysis_data.get("confidence", 1.0)),
        processing_time=0.0,
        raw_response={"simulation": True},
    )
    db.add(analysis)
    await db.commit()

    # ------------------------------------------------------------------
    # 5. Générer le rapport PDF
    # ------------------------------------------------------------------
    call_dict: Dict[str, Any] = {
        "id": str(call.id),
        "created_at": call.created_at.isoformat() if call.created_at else None,
        "duration": call.duration,
        "status": call.status,
    }
    patient_dict: Dict[str, Any] = {
        "nom": patient.nom,
        "prenom": patient.prenom,
        "numero_dossier": patient.numero_dossier,
        "telephone": patient.telephone,
        "service_hospitalisation": patient.service_hospitalisation,
        "diagnostic_principal": getattr(patient, "diagnostic_principal", None),
        "sejour_id": getattr(patient, "sejour_id", ""),
        "visite_id": getattr(patient, "visite_id", ""),
    }
    transcription_dict: Dict[str, Any] = {
        "full_text": transcription.full_text,
        "language": transcription.language,
        "confidence": transcription.confidence,
    }
    analysis_dict: Dict[str, Any] = {
        "pain_level": analysis.pain_level,
        "pain_location": analysis.pain_location,
        "pain_description": analysis.pain_description,
        "has_fever": analysis.has_fever,
        "fever_temperature": analysis.fever_temperature,
        "fever_duration": analysis.fever_duration,
        "takes_medication": analysis.takes_medication,
        "medication_regularity": analysis.medication_regularity,
        "medication_issues": analysis.medication_issues,
        "moral_state": analysis.moral_state,
        "moral_description": analysis.moral_description,
        "summary": analysis.summary,
        "alerts": analysis.alerts,
        "recommendations": analysis.recommendations,
        "risk_score": analysis.risk_score,
    }

    raw_sim = getattr(call, "call_metadata", None)
    call_meta = raw_sim if isinstance(raw_sim, dict) else None

    pdf_path = report_service.generate_call_report(
        call_data=call_dict,
        patient_data=patient_dict,
        transcription_data=transcription_dict,
        analysis_data=analysis_dict,
        call_metadata=call_meta,
        report_type="standard",
    )
    logger.info(f"[SIM] Rapport PDF généré: {pdf_path}")

    # ------------------------------------------------------------------
    # 6. Générer et envoyer l'ORU HL7 vers Mirth (mock)
    # ------------------------------------------------------------------
    hl7_path: Optional[str] = None
    hl7_sent = False
    hl7_detail = ""
    try:
        hl7_path = epicura_hl7_service.generate_oru_message(
            call_data=call_dict,
            patient_data=patient_dict,
            pdf_path=pdf_path,
        )
        send_result = await epicura_hl7_service.send_oru(hl7_path)
        hl7_sent = send_result.get("success", False)
        hl7_detail = send_result.get("detail", "")
        logger.info(f"[SIM] ORU envoyé vers Mirth: success={hl7_sent} | {hl7_detail}")
    except Exception as exc:
        logger.error(f"[SIM] Erreur envoi ORU: {exc}")
        hl7_detail = str(exc)

    # ------------------------------------------------------------------
    # 7. Persister l'enregistrement du rapport
    # ------------------------------------------------------------------
    import os as _os

    file_size = _os.path.getsize(pdf_path) if _os.path.exists(pdf_path) else 0
    report = Report(
        call_id=call.id,
        analysis_id=analysis.id,
        report_type="standard",
        file_path=pdf_path,
        file_size=file_size,
        status="sent" if hl7_sent else "generated",
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    return {
        "success": True,
        "call_id": str(call.id),
        "patient_id": str(patient.id),
        "patient_numero_dossier": patient.numero_dossier,
        "report_id": str(report.id),
        "pdf_path": pdf_path,
        "hl7_path": hl7_path,
        "hl7_sent": hl7_sent,
        "hl7_detail": hl7_detail,
    }


@router.get("/patient/{numero_dossier}")
async def sim_get_patient(
    numero_dossier: str,
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(_require_sim_key),
) -> Dict[str, Any]:
    """
    Vérifie qu'un patient existe en base après un import HL7 ADT.
    Utilisé par le script E2E pour valider l'étape 3.
    """
    result = await db.execute(
        select(Patient).where(Patient.numero_dossier == numero_dossier)
    )
    patient = result.scalar_one_or_none()

    if patient is None:
        # Chercher le dernier patient HL7 comme fallback
        result2 = await db.execute(
            select(Patient)
            .where(Patient.hl7_source == "ADT_MIRTH")
            .order_by(Patient.created_at.desc())
            .limit(1)
        )
        latest = result2.scalar_one_or_none()
        return {
            "found": False,
            "numero_dossier": numero_dossier,
            "latest_hl7_patient": {
                "numero_dossier": latest.numero_dossier,
                "nom": latest.nom,
                "prenom": latest.prenom,
                "hl7_source": latest.hl7_source,
                "next_call_scheduled": latest.next_call_scheduled.isoformat() if latest.next_call_scheduled else None,
            } if latest else None,
        }

    return {
        "found": True,
        "numero_dossier": patient.numero_dossier,
        "nom": patient.nom,
        "prenom": patient.prenom,
        "telephone": patient.telephone,
        "service": patient.service_hospitalisation,
        "sejour_id": getattr(patient, "sejour_id", None),
        "hl7_source": getattr(patient, "hl7_source", None),
        "next_call_scheduled": patient.next_call_scheduled.isoformat() if patient.next_call_scheduled else None,
        "status": patient.status,
    }


@router.get("/status")
async def sim_status(_key: str = Depends(_require_sim_key)) -> Dict[str, Any]:
    """Vérifie que le mode simulation est actif et retourne sa configuration."""
    return {
        "simulation_mode": settings.SIMULATION_MODE,
        "mirth_transport": settings.MIRTH_TRANSPORT,
        "mirth_http_url": settings.MIRTH_HTTP_URL,
        "hl7_auto_schedule": settings.HL7_AUTO_SCHEDULE_CALLS,
        "transfer_mode": settings.TRANSFER_MODE,
    }
