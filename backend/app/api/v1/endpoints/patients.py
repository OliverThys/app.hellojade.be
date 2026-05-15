"""
Endpoints pour la gestion des patients
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, get_pagination, PaginationParams
from app.models.call import Call
from app.models.patient import Patient
from app.models.user import User
from app.schemas.patient import (
    CallbackNoteUpdate,
    CallbackPatientItem,
    CallbacksResponse,
    ManualRecallRequest,
    PatientCreate,
    PatientResponse,
    PatientUpdate,
)
from app.services.audit_service import audit_service
from app.services.gdpr_service import gdpr_service
from app.services.telephony.questionnaire import QUESTIONNAIRE

router = APIRouter()


_ALERT_LABELS: Dict[str, str] = {
    # Q1 — Douleur
    "Q1_douleur":           "Douleur signalée",
    "Q1a_score_douleur":    "Score de douleur élevé",
    "Q1b_empeche_dormir":   "Douleur invalidante (sommeil / mobilité)",
    "Q1c_intolerable":      "Douleur intolérable ou aggravante",
    "Q1d_antidouleurs":     "Antidouleurs insuffisants",
    # Q2/Q3 — Alimentation / Nausées
    "Q2_alimentation":              "Alimentation perturbée",
    "alimentation_non_nausee_non":  "Alimentation anormale sans nausées",
    "Q3_nausees":                   "Nausées ou vomissements",
    "Q3a_nausees_persistantes":     "Nausées persistantes toute la journée",
    "Q3b_vomissements_repetes":     "Vomissements répétés",
    # Q4 — Pansement
    "Q4_pansement":     "Pansement non propre ou non sec",
    "Q4a_sang":         "Saignement au pansement",
    "Q4b_ecoulement":   "Écoulement au pansement",
    # Q5 — Médecin
    "Q5_medecin":           "Consultation médicale depuis la sortie",
    "Q5a_lie_intervention": "Consultation liée à l'opération",
    # Q6 — Autres symptômes
    "Q6_autres_symptomes":  "Symptômes préoccupants (thorax / respiration / urinaire)",
    "Q6a_symptome_detail":  "Description du symptôme signalé",
    # Q7 — Demande de contact
    "Q7_parler_equipe": "Demande de contact avec l'équipe médicale",
}


def _clinical_alert_question_text(meta: Dict[str, Any]) -> Optional[str]:
    """
    Retourne un libellé court et lisible pour un soignant décrivant le motif
    de l'alerte clinique (pas le texte brut de la question posée au patient).
    """
    if meta.get("alert_type") != "clinical":
        return None
    reason = meta.get("alert_reason")
    if not reason or not isinstance(reason, str):
        return None
    return _ALERT_LABELS.get(reason)


@router.get("", response_model=Dict[str, Any])
async def get_patients(
    status_filter: Optional[str] = Query(None, pattern="^(actif|inactif|prioritaire|urgence)$"),
    search: Optional[str] = None,
    pagination: PaginationParams = Depends(get_pagination),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Récupérer la liste des patients avec pagination"""
    
    # Vérifier les permissions
    if not current_user.can_view_patients:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions insuffisantes pour voir les patients",
        )
    
    # Construire la requête de base pour le comptage
    base_stmt = select(Patient)
    
    # Filtrer par statut
    if status_filter:
        base_stmt = base_stmt.where(Patient.status == status_filter)
    
    # Recherche par nom, prénom, numéro de dossier ou téléphone
    if search:
        search_pattern = f"%{search}%"
        base_stmt = base_stmt.where(
            (Patient.nom.ilike(search_pattern))
            | (Patient.prenom.ilike(search_pattern))
            | (Patient.numero_dossier.ilike(search_pattern))
            | (Patient.telephone.ilike(search_pattern))
        )
    
    # Compter le total
    from sqlalchemy import func
    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()
    
    # Construire la requête pour les données
    stmt = base_stmt
    
    # Ordonner et paginer
    stmt = stmt.order_by(Patient.nom, Patient.prenom)
    stmt = stmt.offset(pagination.skip).limit(pagination.limit)
    
    result = await db.execute(stmt)
    patients = result.scalars().all()
    
    # Calculer le nombre de pages
    pages = (total + pagination.limit - 1) // pagination.limit if pagination.limit > 0 else 1
    current_page = (pagination.skip // pagination.limit) + 1 if pagination.limit > 0 else 1
    
    return {
        "items": [PatientResponse.model_validate(patient) for patient in patients],
        "total": total,
        "page": current_page,
        "page_size": pagination.limit,
        "pages": pages,
    }


# ==================== RAPPELS PATIENTS ====================

@router.get("/callbacks", response_model=CallbacksResponse)
async def get_callbacks(
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Retourne les patients triés en 3 catégories pour la vue Rappels :
    - to_recall        : nécessitent un rappel humain (appel échoué ou alerte)
    - ok               : dernier appel réussi sans alerte, ou transféré
    - manually_recalled: déjà rappelés manuellement par un soignant
    """
    if not current_user.can_view_patients:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions insuffisantes pour voir les patients",
        )

    from sqlalchemy.orm import selectinload
    stmt = (
        select(Patient)
        .options(selectinload(Patient.calls))
        .where(Patient.consent_given.is_(True))
        .order_by(Patient.nom, Patient.prenom)
    )
    result = await db.execute(stmt)
    patients = result.scalars().all()

    to_recall: list[CallbackPatientItem] = []
    ok: list[CallbackPatientItem] = []
    unreachable: list[CallbackPatientItem] = []
    manually_recalled_list: list[CallbackPatientItem] = []

    # Statuts Asterisk indiquant que le patient n'a pas décroché
    FAILED_STATUSES = {"no_answer", "busy", "failed", "interrupted"}
    # Raisons contact_failure où le patient était injoignable (pas d'interaction vocale utile)
    UNREACHABLE_REASONS = {"no_response", "call_interrupted", "answering_machine"}

    for patient in patients:
        last_call = patient.calls[0] if patient.calls else None

        meta = (last_call.call_metadata or {}) if last_call else {}
        alert_triggered = bool(meta.get("alert_triggered", False))
        alert_type = meta.get("alert_type")
        alert_reason = meta.get("alert_reason")
        last_status = last_call.status if last_call else None
        alert_question = _clinical_alert_question_text(meta)

        item = CallbackPatientItem(
            id=patient.id,
            nom=patient.nom,
            prenom=patient.prenom,
            telephone=patient.telephone,
            service_hospitalisation=patient.service_hospitalisation,
            date_sortie=patient.date_sortie,
            manually_recalled=patient.manually_recalled,
            manually_recalled_at=patient.manually_recalled_at,
            manually_recalled_by=patient.manually_recalled_by,
            callback_note=patient.callback_note,
            last_call_at=patient.last_call_at,
            last_call_id=last_call.id if last_call else None,
            last_call_status=last_status,
            last_call_alert_triggered=alert_triggered if last_call else None,
            last_call_alert_type=alert_type,
            last_call_alert_reason=alert_reason,
            last_call_alert_question=alert_question,
            updated_at=patient.updated_at,
        )

        if patient.manually_recalled:
            manually_recalled_list.append(item)
            continue

        if not last_call:
            continue

        is_transfer_ok = (last_status == "completed" and alert_type == "transfer")

        # Colonne "À rappeler" : alerte clinique OU transfert échoué
        needs_human_recall = (
            alert_triggered
            and not is_transfer_ok
            and not (alert_type == "contact_failure" and alert_reason in UNREACHABLE_REASONS)
        )

        # Colonne "Non joignable" : patient pas décroché / interrompu / répondeur
        is_unreachable = (
            last_status in FAILED_STATUSES
            or (alert_type == "contact_failure" and alert_reason in UNREACHABLE_REASONS)
        )

        if needs_human_recall:
            to_recall.append(item)
        elif is_unreachable:
            unreachable.append(item)
        else:
            ok.append(item)

    def recall_sort_key(p: CallbackPatientItem) -> int:
        if p.last_call_alert_type == "clinical":
            return 0
        if p.last_call_alert_triggered:
            return 1
        return 2

    to_recall.sort(key=recall_sort_key)

    # Évite qu’un CDN ou le navigateur serve une liste de rappels périmée après une mise à jour.
    response.headers["Cache-Control"] = "no-store, private, max-age=0"
    response.headers["Pragma"] = "no-cache"

    return CallbacksResponse(
        to_recall=to_recall,
        ok=ok,
        unreachable=unreachable,
        manually_recalled=manually_recalled_list,
    )


@router.get("/{patient_id}", response_model=PatientResponse)
async def get_patient(
    patient_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Récupérer un patient par son ID"""
    
    # Vérifier les permissions
    if not current_user.can_view_patients:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions insuffisantes pour voir les patients",
        )
    
    patient = await db.get(Patient, patient_id)
    
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient non trouvé",
        )
    
    return PatientResponse.model_validate(patient)


@router.post("", response_model=PatientResponse)
async def create_patient(
    patient_data: PatientCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Créer un nouveau patient"""
    
    # Vérifier les permissions (admin ou médecin)
    if not current_user.is_medical_staff and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions insuffisantes pour créer un patient",
        )
    
    # Vérifier l'unicité du numéro de dossier
    stmt = select(Patient).where(Patient.numero_dossier == patient_data.numero_dossier)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Un patient avec ce numéro de dossier existe déjà",
        )
    
    # Créer le patient
    patient = Patient(**patient_data.model_dump())
    db.add(patient)
    await db.commit()
    await db.refresh(patient)
    
    return PatientResponse.model_validate(patient)


@router.patch("/{patient_id}", response_model=PatientResponse)
async def update_patient(
    patient_id: UUID,
    patient_update: PatientUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Mettre à jour un patient"""
    
    update_data = patient_update.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Aucun champ fourni pour la mise à jour",
        )

    is_staff_or_admin = bool(current_user.is_medical_staff or current_user.is_admin)
    callback_only = is_staff_or_admin or (
        current_user.can_view_patients
        and set(update_data.keys()) <= {"callback_note"}
    )

    if not callback_only:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions insuffisantes pour modifier un patient",
        )
    
    patient = await db.get(Patient, patient_id)
    
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient non trouvé",
        )
    
    # Appliquer les modifications
    for field, value in update_data.items():
        setattr(patient, field, value)
    # Forcer l’horodatage côté app (onupdate=func.now() ne part pas toujours sur un simple UPDATE asyncpg)
    patient.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(patient)

    return PatientResponse.model_validate(patient)


@router.delete("/{patient_id}")
async def delete_patient(
    patient_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Supprimer un patient (RGPD)"""
    
    # Vérifier les permissions (admin uniquement)
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seuls les administrateurs peuvent supprimer un patient",
        )
    
    patient = await db.get(Patient, patient_id)
    
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient non trouvé",
        )
    
    await db.delete(patient)
    await db.commit()
    
    return {"message": "Patient supprimé avec succès"}

@router.post("/{patient_id}/manual-recall", response_model=PatientResponse)
async def mark_as_manually_recalled(
    patient_id: UUID,
    body: ManualRecallRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Marque un patient comme rappelé manuellement.
    - Pose le flag manually_recalled = True (bloque les retries JADE)
    - Enregistre l'horodatage et le nom du soignant connecté
    - Auto-append une note formatée, suivi de la note libre du soignant
    """
    if not current_user.can_view_patients:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions insuffisantes",
        )

    patient = await db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient non trouvé",
        )

    now = datetime.now(timezone.utc)
    # Nom affiché : full_name depuis IntraID, sinon username
    recalled_by = current_user.full_name or current_user.username

    # Note auto-générée (style logiciel de santé)
    patient.manually_recalled = True
    patient.manually_recalled_at = now
    patient.manually_recalled_by = recalled_by
    patient.callback_note = body.note.strip() if body.note and body.note.strip() else None
    # Annuler tout retry planifié
    patient.next_call_scheduled = None
    patient.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(patient)

    return PatientResponse.model_validate(patient)


@router.patch("/{patient_id}/callback-note", response_model=PatientResponse)
async def update_callback_note(
    patient_id: UUID,
    body: CallbackNoteUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Met à jour la note de rappel d'un patient (sans modifier le statut)."""
    if not current_user.can_view_patients:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissions insuffisantes")

    patient = await db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient non trouvé")

    patient.callback_note = body.note
    patient.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(patient)
    return PatientResponse.model_validate(patient)


@router.delete("/{patient_id}/manual-recall", response_model=PatientResponse)
async def unmark_manual_recall(
    patient_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Annule le statut 'rappelé manuellement' d'un patient.
    Remet le patient dans le flux normal de JADE.
    """
    if not current_user.can_view_patients:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions insuffisantes",
        )

    patient = await db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient non trouvé",
        )

    patient.manually_recalled = False
    patient.manually_recalled_at = None
    patient.manually_recalled_by = None
    # On conserve callback_note comme historique

    await db.commit()
    await db.refresh(patient)

    return PatientResponse.model_validate(patient)


# ==================== ENDPOINTS RGPD ====================

@router.get("/{patient_id}/export")
async def export_patient_data(
    request: Request,
    patient_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    Exporter toutes les données d'un patient (conformité RGPD)
    
    Nécessite les permissions pour voir les patients.
    """
    # Vérifier les permissions
    if not current_user.can_view_patients:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions insuffisantes",
        )
    
    try:
        # Exporter les données
        export_data = await gdpr_service.export_patient_data(
            db=db,
            patient_id=patient_id,
            user_id=current_user.id,
            user_email=current_user.email,
        )
        
        # Convertir en JSON
        import json
        json_content = json.dumps(export_data, indent=2, ensure_ascii=False, default=str)
        
        return Response(
            content=json_content,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="patient_data_{patient_id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json"'
            },
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de l'export: {str(e)}",
        )


@router.delete("/{patient_id}/gdpr-delete")
async def gdpr_delete_patient(
    patient_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Supprimer/anonymiser les données d'un patient (conformité RGPD)
    
    Nécessite les permissions admin. Cette action anonymise toutes les données
    personnelles du patient conformément au RGPD.
    """
    # Vérifier les permissions (admin uniquement)
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seuls les administrateurs peuvent supprimer des données patient",
        )
    
    try:
        result = await gdpr_service.delete_patient_data(
            db=db,
            patient_id=patient_id,
            user_id=current_user.id,
            user_email=current_user.email,
        )
        
        return result
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la suppression: {str(e)}",
        )


@router.get("/{patient_id}/audit-trail")
async def get_patient_audit_trail(
    patient_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Récupérer la traçabilité complète des accès aux données d'un patient
    
    Nécessite les permissions pour voir les patients.
    """
    # Vérifier les permissions
    if not current_user.can_view_patients:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions insuffisantes",
        )
    
    # Vérifier que le patient existe
    patient = await db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient non trouvé",
        )
    
    # Logger l'accès à la traçabilité
    await audit_service.log_action(
        db=db,
        action="view_audit_trail",
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type="patient",
        resource_id=patient_id,
        resource_name=f"{patient.prenom} {patient.nom}",
    )
    
    # Récupérer la traçabilité
    audit_trail = await gdpr_service.get_patient_audit_trail(
        db=db,
        patient_id=patient_id,
    )
    
    return {
        "patient_id": str(patient_id),
        "patient_name": f"{patient.prenom} {patient.nom}",
        "audit_logs": audit_trail,
        "total_accesses": len(audit_trail),
    }
