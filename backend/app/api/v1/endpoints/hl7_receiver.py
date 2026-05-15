"""
Endpoint récepteur HL7 pour les messages ADT envoyés par Mirth (Epicura).

Mirth envoie des messages HL7 v2.2 ADT via HTTP POST.
Authentification par API key dédiée (machine-to-machine, pas JWT/SAML2).
"""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.database import get_db
from app.models.care_unit import CareUnit
from app.models.patient import Patient
from app.services.hl7_adt_service import (
    HL7ParseError,
    build_ack_message,
    parse_adt_message,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/hl7")


async def verify_hl7_api_key(
    x_hl7_api_key: str = Header(..., alias="X-HL7-API-Key"),
) -> str:
    """Vérifie la clé API HL7 partagée avec Mirth."""
    if not settings.HL7_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="HL7 integration not configured",
        )
    if x_hl7_api_key != settings.HL7_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid HL7 API key",
        )
    return x_hl7_api_key


@router.post("/adt")
async def receive_adt(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_hl7_api_key),
) -> Any:
    """
    Reçoit un message HL7 ADT depuis Mirth.

    Content-Type attendu : text/plain ou x-application/hl7-v2+er7
    Body : message HL7 brut (pipe-delimited ER7)

    Retourne un ACK HL7 (AA=succès, AE=erreur).
    """
    raw_body = (await request.body()).decode("utf-8", errors="replace")

    if not raw_body.strip():
        return _ack_response("", "AR", "Empty message body")

    try:
        parsed = parse_adt_message(raw_body)
    except HL7ParseError as e:
        logger.warning(f"HL7 parse error: {e}")
        return _ack_response(raw_body, "AE", str(e))

    event = parsed["event_type"]
    patient_data = parsed["patient"]
    visit_data = parsed["visit"]

    logger.info(
        f"HL7 ADT reçu: {event} | Patient: {patient_data.get('nom')} {patient_data.get('prenom')} "
        f"| Dossier: {patient_data.get('numero_dossier')} | Service: {visit_data.get('service_code')}"
    )

    # Seuls A03 (sortie) et A08 (mise à jour) sont traités
    if event not in ("A03", "A08"):
        logger.info(f"HL7 ADT événement {event} ignoré (seuls A03/A08 traités)")
        return _ack_response(raw_body, "AA", f"Event {event} acknowledged but not processed")

    # --- Upsert du patient ---
    numero_dossier = patient_data.get("numero_dossier")
    if not numero_dossier:
        return _ack_response(raw_body, "AE", "PID.3 (numero_dossier) manquant")

    # Chercher patient existant par numero_dossier
    result = await db.execute(
        select(Patient).where(Patient.numero_dossier == numero_dossier)
    )
    patient = result.scalar_one_or_none()

    if patient:
        # Mise à jour
        _update_patient_from_hl7(patient, patient_data, visit_data)
        logger.info(f"Patient mis à jour: {patient.numero_dossier}")
    else:
        # Création
        oracle_id = patient_data.get("oracle_patient_id")
        if not oracle_id:
            # Générer un ID si non fourni par HL7
            oracle_id_int = abs(hash(numero_dossier)) % (10**9)
        else:
            try:
                oracle_id_int = int(oracle_id)
            except (ValueError, TypeError):
                oracle_id_int = abs(hash(oracle_id)) % (10**9)

        patient = Patient(
            oracle_patient_id=oracle_id_int,
            numero_dossier=numero_dossier,
            nom=patient_data.get("nom", ""),
            prenom=patient_data.get("prenom", ""),
            telephone=patient_data.get("telephone"),
            date_naissance=patient_data.get("date_naissance"),
            sexe=patient_data.get("sexe"),
            adresse=patient_data.get("adresse"),
            ville=patient_data.get("ville"),
            code_postal=patient_data.get("code_postal"),
            service_hospitalisation=visit_data.get("service_code"),
            medecin_responsable=visit_data.get("medecin_responsable"),
            date_admission=visit_data.get("date_admission"),
            date_sortie=visit_data.get("date_sortie"),
            sejour_id=visit_data.get("sejour_id"),
            visite_id=visit_data.get("visite_id"),
            hl7_source="ADT_MIRTH",
            status="actif",
            consent_given=True,  # Consentement recueilli à l'admission
        )
        db.add(patient)
        logger.info(f"Nouveau patient créé depuis HL7: {numero_dossier}")

    # Planifier appel automatique si configuré et c'est une sortie (A03)
    if event == "A03" and settings.HL7_AUTO_SCHEDULE_CALLS:
        if patient.telephone and not patient.next_call_scheduled:
            from datetime import timedelta, timezone
            from app.services.call_settings_service import (
                call_settings_service,
                next_valid_window,
            )
            cs = await call_settings_service.get()
            delay_hours = int(cs.get("delay_after_discharge_hours", 24))
            # Point de départ : date_sortie du HL7 si disponible, sinon maintenant
            discharge_time = visit_data.get("date_sortie")
            if discharge_time is None:
                discharge_time = datetime.now(timezone.utc)
            elif discharge_time.tzinfo is None:
                discharge_time = discharge_time.replace(tzinfo=timezone.utc)
            raw_next = discharge_time + timedelta(hours=delay_hours)
            # Ajuster à la prochaine plage d'appel valide (jour + fenêtre horaire)
            scheduled = next_valid_window(raw_next, cs)
            patient.next_call_scheduled = scheduled
            logger.info(
                f"Appel planifié pour {patient.numero_dossier} "
                f"le {scheduled.isoformat()} "
                f"(sortie + {delay_hours}h → fenêtre valide)"
            )

    await db.commit()

    return _ack_response(raw_body, "AA")


@router.post("/adt/batch")
async def receive_adt_batch(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_hl7_api_key),
) -> Any:
    """
    Reçoit un batch de messages HL7 ADT.

    Les messages sont séparés par des lignes vides ou des marqueurs MSH.
    """
    raw_body = (await request.body()).decode("utf-8", errors="replace")

    if not raw_body.strip():
        return {"processed": 0, "errors": 0, "details": []}

    # Séparer les messages (chaque MSH commence un nouveau message)
    messages = _split_hl7_batch(raw_body)

    processed = 0
    errors = 0
    details = []

    for i, msg in enumerate(messages):
        try:
            parsed = parse_adt_message(msg)
            numero_dossier = parsed["patient"].get("numero_dossier", "?")

            # Même logique que receive_adt mais inline
            event = parsed["event_type"]
            if event not in ("A03", "A08"):
                details.append({"index": i, "status": "skipped", "event": event})
                continue

            patient_data = parsed["patient"]
            visit_data = parsed["visit"]
            nd = patient_data.get("numero_dossier")
            if not nd:
                errors += 1
                details.append({"index": i, "status": "error", "reason": "no numero_dossier"})
                continue

            result = await db.execute(
                select(Patient).where(Patient.numero_dossier == nd)
            )
            patient = result.scalar_one_or_none()

            if patient:
                _update_patient_from_hl7(patient, patient_data, visit_data)
            else:
                oracle_id = patient_data.get("oracle_patient_id")
                oracle_id_int = int(oracle_id) if oracle_id and oracle_id.isdigit() else abs(hash(nd)) % (10**9)
                patient = Patient(
                    oracle_patient_id=oracle_id_int,
                    numero_dossier=nd,
                    nom=patient_data.get("nom", ""),
                    prenom=patient_data.get("prenom", ""),
                    telephone=patient_data.get("telephone"),
                    date_naissance=patient_data.get("date_naissance"),
                    sexe=patient_data.get("sexe"),
                    adresse=patient_data.get("adresse"),
                    ville=patient_data.get("ville"),
                    code_postal=patient_data.get("code_postal"),
                    service_hospitalisation=visit_data.get("service_code"),
                    medecin_responsable=visit_data.get("medecin_responsable"),
                    date_admission=visit_data.get("date_admission"),
                    date_sortie=visit_data.get("date_sortie"),
                    sejour_id=visit_data.get("sejour_id"),
                    visite_id=visit_data.get("visite_id"),
                    hl7_source="ADT_MIRTH",
                    status="actif",
                    consent_given=True,
                )
                db.add(patient)

            processed += 1
            details.append({"index": i, "status": "ok", "numero_dossier": nd})

        except Exception as e:
            errors += 1
            details.append({"index": i, "status": "error", "reason": str(e)})

    await db.commit()

    logger.info(f"HL7 ADT batch: {processed} traités, {errors} erreurs sur {len(messages)} messages")

    return {
        "processed": processed,
        "errors": errors,
        "total": len(messages),
        "details": details,
    }


@router.get("/status")
async def hl7_status(
    _api_key: str = Depends(verify_hl7_api_key),
) -> Any:
    """Endpoint de healthcheck pour Mirth."""
    return {
        "status": "ok",
        "service": "HelloJADE HL7 Receiver",
        "version": "2.2",
        "supported_events": ["ADT^A03", "ADT^A08"],
    }


def _update_patient_from_hl7(
    patient: Patient,
    patient_data: dict,
    visit_data: dict,
) -> None:
    """Met à jour les champs d'un patient existant depuis les données HL7."""
    # Ne pas écraser les champs remplis si HL7 envoie des valeurs vides
    if patient_data.get("nom"):
        patient.nom = patient_data["nom"]
    if patient_data.get("prenom"):
        patient.prenom = patient_data["prenom"]
    if patient_data.get("telephone"):
        patient.telephone = patient_data["telephone"]
    if patient_data.get("date_naissance"):
        patient.date_naissance = patient_data["date_naissance"]
    if patient_data.get("sexe"):
        patient.sexe = patient_data["sexe"]
    if patient_data.get("adresse"):
        patient.adresse = patient_data["adresse"]
    if patient_data.get("ville"):
        patient.ville = patient_data["ville"]
    if patient_data.get("code_postal"):
        patient.code_postal = patient_data["code_postal"]

    if visit_data.get("service_code"):
        patient.service_hospitalisation = visit_data["service_code"]
    if visit_data.get("medecin_responsable"):
        patient.medecin_responsable = visit_data["medecin_responsable"]
    if visit_data.get("date_admission"):
        patient.date_admission = visit_data["date_admission"]
    if visit_data.get("date_sortie"):
        patient.date_sortie = visit_data["date_sortie"]
    if visit_data.get("sejour_id"):
        patient.sejour_id = visit_data["sejour_id"]
    if visit_data.get("visite_id"):
        patient.visite_id = visit_data["visite_id"]

    patient.hl7_source = "ADT_MIRTH"
    patient.status = "actif"


def _split_hl7_batch(raw: str) -> list[str]:
    """Sépare un batch de messages HL7 (chaque MSH commence un message)."""
    # Normaliser les fins de lignes
    raw = raw.replace("\r\n", "\r").replace("\n", "\r")
    lines = raw.split("\r")

    messages = []
    current = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("MSH") and current:
            messages.append("\r".join(current))
            current = []
        current.append(stripped)

    if current:
        messages.append("\r".join(current))

    return messages


def _ack_response(original_msg: str, code: str, error: str = "") -> dict:
    """Construit la réponse JSON + ACK HL7."""
    ack = build_ack_message(original_msg, code, error)
    return {
        "ack_code": code,
        "ack_message": ack,
        "error": error if code != "AA" else None,
    }
