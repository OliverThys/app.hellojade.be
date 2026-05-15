"""
Admin — bibliothèque de questionnaires, affectations par service, paramètres d'appel.

Questionnaires
  GET    /admin/questionnaires                   liste de la bibliothèque
  POST   /admin/questionnaires                   créer
  GET    /admin/questionnaires/{id}              charger
  PUT    /admin/questionnaires/{id}              sauvegarder
  DELETE /admin/questionnaires/{id}              supprimer (interdit si assigné)
  POST   /admin/questionnaires/{id}/duplicate    dupliquer

Affectations
  GET    /admin/assignments                      état de toutes les affectations
  PUT    /admin/assignments/default              changer le questionnaire par défaut
  DELETE /admin/assignments/default              supprimer l'affectation défaut (fallback Python)
  PUT    /admin/assignments/{care_unit_id}       affecter à un service
  DELETE /admin/assignments/{care_unit_id}       retirer l'affectation (retombe sur défaut)
  POST   /admin/assignments/bulk                 affecter à plusieurs / tous les services

Paramètres d'appel
  GET    /admin/call-settings
  PUT    /admin/call-settings

La configuration applicative (Azure, Mistral, Asterisk, etc.) se fait via le .env.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Literal, Optional, Union
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_admin_user
from app.models.care_unit import CareUnit
from app.models.questionnaire import Questionnaire, QuestionnaireAssignment
from app.models.setting import Setting
from app.models.user import User
from app.core.logging import get_logger
from app.services.audit_service import audit_service

logger = get_logger(__name__)
router = APIRouter()

_KEY_CALL_SETTINGS    = "admin.call_settings"
_KEY_FACTORY          = "questionnaire.factory_default_id"        # UUID questionnaire patient usine
_KEY_FACTORY_PROCHE   = "questionnaire.factory_proche_default_id" # UUID questionnaire proche usine


# ── Schémas Pydantic ────────────────────────────────────────────────────────

class FollowUpDTO(BaseModel):
    question_id: str
    text: str
    type: Literal["yesno", "score", "open", "choice"] = "yesno"
    condition: Optional[Union[str, List[str]]] = None
    condition_parent_id: Optional[str] = None
    record_duration: int = 10
    alert_if: Optional[str] = None
    alert_if_gte: Optional[float] = None
    alert_type: Literal["clinical", "transfer"] = "clinical"
    choices: Optional[List[str]] = None
    optional: bool = False
    is_active: bool = True


class MainQuestionDTO(BaseModel):
    question_id: str
    text: str
    type: Literal["yesno", "score", "open", "choice"] = "yesno"
    order: int = 0
    is_active: bool = True
    record_duration: int = 30
    alert_if: Optional[str] = None
    alert_if_gte: Optional[float] = None
    alert_type: Literal["clinical", "transfer"] = "clinical"
    choices: Optional[List[str]] = None
    follow_ups: List[FollowUpDTO] = []


class MessagesDTO(BaseModel):
    welcome: str = ""
    outro_normal: str = ""
    outro_alert: str = ""
    outro_transfer_failed: str = ""


class QuestionnaireCreateDTO(BaseModel):
    name: str
    description: Optional[str] = None
    questions: List[MainQuestionDTO] = []
    messages: MessagesDTO = MessagesDTO()


class QuestionnaireUpdateDTO(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    questions: Optional[List[MainQuestionDTO]] = None
    messages: Optional[MessagesDTO] = None


class QuestionnaireOut(BaseModel):
    id: str
    name: str
    description: Optional[str]
    questions: List[MainQuestionDTO]
    messages: MessagesDTO
    is_factory_default: bool
    assigned_to: List[str]  # noms des services assignés ("Défaut" si NULL)
    created_at: str
    updated_at: str


class QuestionnaireIdBody(BaseModel):
    questionnaire_id: UUID


class QuestionnaireDuplicateBody(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)


class AssignmentOut(BaseModel):
    care_unit_id: Optional[str]         # None = défaut
    care_unit_name: str                  # "Défaut" si None
    care_unit_code: Optional[str]
    questionnaire_id: Optional[str]      # questionnaire patient
    questionnaire_name: Optional[str]
    proche_questionnaire_id: Optional[str] = None   # questionnaire proche (None = fallback patient)
    proche_questionnaire_name: Optional[str] = None
    care_unit_active: Optional[bool] = None  # None pour la ligne « Défaut »


class CallSettingsPayload(BaseModel):
    delay_after_discharge_hours: int = Field(default=24, ge=1, le=168)
    call_window_start: str = "09:00"
    call_window_end: str = "19:00"
    allowed_days: List[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]] = [
        "mon", "tue", "wed", "thu", "fri"
    ]
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_delay_hours: int = Field(default=4, ge=1, le=48)
    amd_behavior: Literal["retry", "skip"] = "retry"
    max_call_duration_minutes: int = Field(default=10, ge=3, le=30)
    silence_timeout_seconds: int = Field(default=1, ge=1, le=30)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _q_to_out(q: Questionnaire, assigned_names: List[str]) -> QuestionnaireOut:
    qs = [MainQuestionDTO.model_validate(x) for x in (q.questions or [])]
    msgs = MessagesDTO.model_validate(q.messages) if q.messages else MessagesDTO()
    return QuestionnaireOut(
        id=str(q.id),
        name=q.name,
        description=q.description,
        questions=qs,
        messages=msgs,
        is_factory_default=q.is_factory_default,
        assigned_to=assigned_names,
        created_at=q.created_at.isoformat(),
        updated_at=q.updated_at.isoformat(),
    )


async def _assignment_names_map(db: AsyncSession) -> Dict[UUID, List[str]]:
    """Pour chaque questionnaire_id, liste des libellés d'affectation (patient + proche)."""
    assignments = list(
        (await db.execute(select(QuestionnaireAssignment))).scalars().all()
    )
    care_units = list((await db.execute(select(CareUnit))).scalars().all())
    cu_by_id = {c.id: c for c in care_units}
    out: Dict[UUID, List[str]] = {}

    def _label(a: QuestionnaireAssignment, role_suffix: str = "") -> str:
        if a.care_unit_id is None:
            return f"Défaut{role_suffix}"
        cu = cu_by_id.get(a.care_unit_id)
        name = cu.name if cu else str(a.care_unit_id)
        return f"{name}{role_suffix}"

    for a in assignments:
        # Questionnaire patient
        qid = a.questionnaire_id
        out.setdefault(qid, [])
        out[qid].append(_label(a))
        # Questionnaire proche (si différent)
        if a.proche_questionnaire_id and a.proche_questionnaire_id != a.questionnaire_id:
            pqid = a.proche_questionnaire_id
            out.setdefault(pqid, [])
            out[pqid].append(_label(a, " (proche)"))
    return out


def _validate_questionnaire_questions(questions: List[MainQuestionDTO]) -> None:
    """Vérifie identifiants uniques et champs requis (évite KeyError au runtime ARI)."""
    seen_main: set[str] = set()
    for m in questions:
        qid = (m.question_id or "").strip()
        if not qid:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Chaque question doit avoir un identifiant (question_id) non vide",
            )
        if qid in seen_main:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Identifiant de question dupliqué : {qid}",
            )
        seen_main.add(qid)
        if not (m.text or "").strip():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Texte vide pour la question « {qid} »",
            )
        if m.type == "choice" and not m.choices:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"La question « {qid} » est de type « choix » mais n'a aucun choix défini",
            )
        seen_fu: set[str] = set()
        for fu in m.follow_ups:
            fid = (fu.question_id or "").strip()
            if not fid:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail=f"Sous-question sans identifiant (parent {qid})",
                )
            if fid in seen_fu:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail=f"Sous-question dupliquée « {fid} » sous {qid}",
                )
            seen_fu.add(fid)
            if not (fu.text or "").strip():
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail=f"Texte vide pour la sous-question « {fid} »",
                )
            if fu.type == "choice" and not fu.choices:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail=f"La sous-question « {fid} » est de type « choix » mais n'a aucun choix défini",
                )


async def _get_setting(db: AsyncSession, key: str) -> Optional[Any]:
    row = await db.scalar(select(Setting).where(Setting.key == key))
    if row is None:
        return None
    v = row.value
    if isinstance(v, dict) and "value" in v and len(v) == 1:
        return v["value"]
    return v


async def _set_setting(db: AsyncSession, key: str, value: Any, category: str = "admin") -> None:
    row = await db.scalar(select(Setting).where(Setting.key == key))
    if row:
        row.previous_value = row.value
        row.value = {"value": value} if not isinstance(value, dict) else value
    else:
        db.add(Setting(
            key=key,
            value={"value": value} if not isinstance(value, dict) else value,
            category=category,
        ))
    await db.commit()


def _build_factory_data() -> tuple[List[Dict], Dict]:
    """Construit questions + messages depuis questionnaire.py (code source)."""
    from app.services.telephony.questionnaire import (
        QUESTIONNAIRE,
        WELCOME_MESSAGE,
        CLOSING_MESSAGE_NORMAL,
        CLOSING_MESSAGE_ALERT,
        CLOSING_MESSAGE_TRANSFER_FAILED,
    )

    def _fu(fu: Dict) -> Dict:
        return {
            "question_id": fu["id"],
            "text": fu["question"],
            "type": fu.get("type", "yesno"),
            "condition": fu.get("condition"),
            "condition_parent_id": fu.get("condition_parent_id"),
            "record_duration": fu.get("record_duration", 10),
            "alert_if": fu.get("alert_if"),
            "alert_if_gte": fu.get("alert_if_gte"),
            "alert_type": fu.get("alert_type", "clinical"),
            "choices": fu.get("choices"),
            "optional": fu.get("optional", False),
            "is_active": True,
        }

    questions = [
        {
            "question_id": q["id"],
            "text": q["question"],
            "type": q.get("type", "yesno"),
            "order": i,
            "is_active": True,
            "record_duration": q.get("record_duration", 30),
            "alert_if": q.get("alert_if"),
            "alert_if_gte": q.get("alert_if_gte"),
            "alert_type": q.get("alert_type", "clinical"),
            "choices": q.get("choices"),
            "follow_ups": [_fu(fu) for fu in q.get("follow_ups", [])],
        }
        for i, q in enumerate(QUESTIONNAIRE)
    ]

    messages = {
        "welcome": WELCOME_MESSAGE,
        "outro_normal": CLOSING_MESSAGE_NORMAL,
        "outro_alert": CLOSING_MESSAGE_ALERT,
        "outro_transfer_failed": CLOSING_MESSAGE_TRANSFER_FAILED,
    }

    return questions, messages


def _build_factory_proche_data() -> tuple[List[Dict], Dict]:
    """Construit le questionnaire proche usine : textes à la 3e personne depuis questionnaire.py."""
    from app.services.telephony.questionnaire import (
        QUESTIONNAIRE,
        WELCOME_MESSAGE,
        CLOSING_MESSAGE_NORMAL_PROCHE,
        CLOSING_MESSAGE_ALERT,
        CLOSING_MESSAGE_TRANSFER_FAILED_PROCHE,
    )

    def _fu(fu: Dict) -> Dict:
        return {
            "question_id": fu["id"],
            "text": fu.get("question_proche") or fu["question"],
            "type": fu.get("type", "yesno"),
            "condition": fu.get("condition"),
            "condition_parent_id": fu.get("condition_parent_id"),
            "record_duration": fu.get("record_duration", 10),
            "alert_if": fu.get("alert_if"),
            "alert_if_gte": fu.get("alert_if_gte"),
            "alert_type": fu.get("alert_type", "clinical"),
            "choices": fu.get("choices"),
            "optional": fu.get("optional", False),
            "is_active": True,
        }

    questions = [
        {
            "question_id": q["id"],
            "text": q.get("question_proche") or q["question"],
            "type": q.get("type", "yesno"),
            "order": i,
            "is_active": True,
            "record_duration": q.get("record_duration", 30),
            "alert_if": q.get("alert_if"),
            "alert_if_gte": q.get("alert_if_gte"),
            "alert_type": q.get("alert_type", "clinical"),
            "choices": q.get("choices"),
            "follow_ups": [_fu(fu) for fu in q.get("follow_ups", [])],
        }
        for i, q in enumerate(QUESTIONNAIRE)
    ]

    messages = {
        "welcome": WELCOME_MESSAGE,
        "outro_normal": CLOSING_MESSAGE_NORMAL_PROCHE,
        "outro_alert": CLOSING_MESSAGE_ALERT,
        "outro_transfer_failed": CLOSING_MESSAGE_TRANSFER_FAILED_PROCHE,
    }

    return questions, messages


async def _seed_proche_factory_if_needed(db: AsyncSession) -> None:
    """Crée le questionnaire proche usine si absent (backfill pour installations existantes)."""
    existing_proche_id = await _get_setting(db, _KEY_FACTORY_PROCHE)
    if existing_proche_id:
        try:
            uid = UUID(str(existing_proche_id))
        except (ValueError, TypeError):
            uid = None
        if uid is not None and await db.get(Questionnaire, uid):
            return  # déjà en place

    logger.info("[Admin] Backfill questionnaire proche d'usine manquant")
    proche_questions, proche_messages = _build_factory_proche_data()
    factory_proche = Questionnaire(
        name="Questionnaire d'usine — Proche",
        description="Version proche (3e personne) livrée lors du déploiement — ne pas modifier.",
        questions=proche_questions,
        messages=proche_messages,
        is_factory_default=True,
    )
    db.add(factory_proche)
    await db.flush()

    # Injecter proche_questionnaire_id sur tous les assignments qui n'en ont pas
    all_assignments = list(
        (await db.execute(select(QuestionnaireAssignment))).scalars().all()
    )
    for a in all_assignments:
        if not a.proche_questionnaire_id:
            a.proche_questionnaire_id = factory_proche.id

    fac_proche_setting = await db.scalar(select(Setting).where(Setting.key == _KEY_FACTORY_PROCHE))
    if fac_proche_setting:
        fac_proche_setting.value = {"value": str(factory_proche.id)}
    else:
        db.add(Setting(key=_KEY_FACTORY_PROCHE, value={"value": str(factory_proche.id)}, category="system"))

    await db.commit()
    logger.info(f"[Admin] Questionnaire proche d'usine créé (backfill) : {factory_proche.id}")


async def seed_factory_default_if_needed(db: AsyncSession) -> None:
    """
    Appelé au démarrage. Crée les questionnaires d'usine (patient + proche) une seule fois
    et les assigne comme défaut. Gère le backfill proche sur les installations existantes.
    """
    existing_id = await _get_setting(db, _KEY_FACTORY)
    if existing_id:
        try:
            uid = UUID(str(existing_id))
        except (ValueError, TypeError):
            uid = None
        if uid is not None:
            row = await db.get(Questionnaire, uid)
            if row:
                # Patient factory OK — vérifier si le proche existe aussi
                await _seed_proche_factory_if_needed(db)
                logger.debug("[Admin] Questionnaire d'usine déjà en base")
                return
        stale = await db.scalar(select(Setting).where(Setting.key == _KEY_FACTORY))
        if stale:
            await db.delete(stale)
            await db.flush()
            logger.warning("[Admin] Setting factory_default_id orphelin — recréation du questionnaire d'usine")

    logger.info("[Admin] Premier démarrage — création des questionnaires d'usine (patient + proche)")
    questions, messages = _build_factory_data()
    proche_questions, proche_messages = _build_factory_proche_data()

    factory = Questionnaire(
        name="Questionnaire d'usine — Patient",
        description="Version patient livrée lors du déploiement — ne pas modifier.",
        questions=questions,
        messages=messages,
        is_factory_default=True,
    )
    db.add(factory)

    factory_proche = Questionnaire(
        name="Questionnaire d'usine — Proche",
        description="Version proche (3e personne) livrée lors du déploiement — ne pas modifier.",
        questions=proche_questions,
        messages=proche_messages,
        is_factory_default=True,
    )
    db.add(factory_proche)
    await db.flush()

    # Assignation par défaut si aucune n'existe
    default_assignment = await db.scalar(
        select(QuestionnaireAssignment).where(QuestionnaireAssignment.care_unit_id.is_(None))
    )
    if not default_assignment:
        db.add(QuestionnaireAssignment(
            care_unit_id=None,
            questionnaire_id=factory.id,
            proche_questionnaire_id=factory_proche.id,
        ))
    else:
        # Backfill proche_questionnaire_id si absent
        if not default_assignment.proche_questionnaire_id:
            default_assignment.proche_questionnaire_id = factory_proche.id

    fac_setting = await db.scalar(select(Setting).where(Setting.key == _KEY_FACTORY))
    if fac_setting:
        fac_setting.value = {"value": str(factory.id)}
        fac_setting.category = "system"
    else:
        db.add(Setting(key=_KEY_FACTORY, value={"value": str(factory.id)}, category="system"))

    fac_proche_setting = await db.scalar(select(Setting).where(Setting.key == _KEY_FACTORY_PROCHE))
    if fac_proche_setting:
        fac_proche_setting.value = {"value": str(factory_proche.id)}
        fac_proche_setting.category = "system"
    else:
        db.add(Setting(key=_KEY_FACTORY_PROCHE, value={"value": str(factory_proche.id)}, category="system"))

    # Paramètres d'appel par défaut
    cs_exists = await db.scalar(select(Setting).where(Setting.key == _KEY_CALL_SETTINGS))
    if not cs_exists:
        db.add(Setting(
            key=_KEY_CALL_SETTINGS,
            value=CallSettingsPayload().model_dump(),
            category="admin",
        ))

    await db.commit()
    logger.info(f"[Admin] Questionnaires d'usine créés — patient: {factory.id}, proche: {factory_proche.id}")


# ── Endpoints bibliothèque ──────────────────────────────────────────────────

@router.get("/questionnaires", response_model=List[QuestionnaireOut])
async def list_questionnaires(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> List[QuestionnaireOut]:
    rows = list((await db.execute(
        select(Questionnaire).order_by(Questionnaire.created_at.asc())
    )).scalars().all())
    names_map = await _assignment_names_map(db)
    return [_q_to_out(q, names_map.get(q.id, [])) for q in rows]


@router.post("/questionnaires", response_model=QuestionnaireOut, status_code=201)
async def create_questionnaire(
    request: Request,
    payload: QuestionnaireCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> QuestionnaireOut:
    if payload.questions:
        _validate_questionnaire_questions(payload.questions)
    q = Questionnaire(
        name=payload.name,
        description=payload.description,
        questions=[m.model_dump() for m in payload.questions],
        messages=payload.messages.model_dump(),
        is_factory_default=False,
    )
    db.add(q)
    await db.commit()
    await db.refresh(q)
    logger.info(f"[Admin] Questionnaire créé : {q.name!r} ({q.id})")
    await audit_service.log_action(
        db,
        action="admin_questionnaire_create",
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type="questionnaire",
        resource_id=q.id,
        resource_name=q.name,
        request=request,
    )
    return _q_to_out(q, [])


@router.get("/questionnaires/{q_id}", response_model=QuestionnaireOut)
async def get_questionnaire(
    q_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> QuestionnaireOut:
    q = await db.get(Questionnaire, q_id)
    if not q:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Questionnaire introuvable")
    names_map = await _assignment_names_map(db)
    return _q_to_out(q, names_map.get(q.id, []))


@router.put("/questionnaires/{q_id}", response_model=QuestionnaireOut)
async def update_questionnaire(
    request: Request,
    q_id: UUID,
    payload: QuestionnaireUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> QuestionnaireOut:
    q = await db.get(Questionnaire, q_id)
    if not q:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Questionnaire introuvable")
    if q.is_factory_default:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Le questionnaire d'usine ne peut pas être modifié — dupliquez-le pour créer une variante",
        )
    if payload.name is not None:
        q.name = payload.name
    if payload.description is not None:
        q.description = payload.description
    if payload.questions is not None:
        _validate_questionnaire_questions(payload.questions)
        q.questions = [m.model_dump() for m in payload.questions]
    if payload.messages is not None:
        q.messages = payload.messages.model_dump()
    await db.commit()
    await db.refresh(q)
    names_map = await _assignment_names_map(db)
    logger.info(f"[Admin] Questionnaire mis à jour : {q.name!r}")
    await audit_service.log_action(
        db,
        action="admin_questionnaire_update",
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type="questionnaire",
        resource_id=q.id,
        resource_name=q.name,
        request=request,
    )
    return _q_to_out(q, names_map.get(q.id, []))


@router.delete("/questionnaires/{q_id}")
async def delete_questionnaire(
    request: Request,
    q_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> Response:
    q = await db.get(Questionnaire, q_id)
    if not q:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Questionnaire introuvable")
    if q.is_factory_default:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Le questionnaire d'usine ne peut pas être supprimé")
    # Vérifier qu'il n'est pas assigné
    count = (await db.execute(
        select(QuestionnaireAssignment).where(QuestionnaireAssignment.questionnaire_id == q_id)
    )).scalars().all()
    if count:
        services = ", ".join(
            ("Défaut" if a.care_unit_id is None else str(a.care_unit_id))
            for a in count
        )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Ce questionnaire est encore assigné à : {services}. Réaffectez ces services avant de supprimer.",
        )
    q_name = q.name
    await db.delete(q)
    await db.commit()
    logger.info(f"[Admin] Questionnaire supprimé : {q_name!r}")
    await audit_service.log_action(
        db,
        action="admin_questionnaire_delete",
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type="questionnaire",
        resource_id=q_id,
        resource_name=q_name,
        request=request,
    )
    return Response(status_code=204)


@router.post("/questionnaires/{q_id}/duplicate", response_model=QuestionnaireOut, status_code=201)
async def duplicate_questionnaire(
    request: Request,
    q_id: UUID,
    body: QuestionnaireDuplicateBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> QuestionnaireOut:
    q = await db.get(Questionnaire, q_id)
    if not q:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Questionnaire introuvable")
    new_name = (body.name or "").strip() or f"Copie de {q.name}"
    copy_q = Questionnaire(
        name=new_name,
        description=q.description,
        questions=copy.deepcopy(q.questions),
        messages=copy.deepcopy(q.messages),
        is_factory_default=False,
    )
    db.add(copy_q)
    await db.commit()
    await db.refresh(copy_q)
    logger.info(f"[Admin] Questionnaire dupliqué : {new_name!r}")
    await audit_service.log_action(
        db,
        action="admin_questionnaire_duplicate",
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type="questionnaire",
        resource_id=copy_q.id,
        resource_name=new_name,
        details={"source_id": str(q_id)},
        request=request,
    )
    return _q_to_out(copy_q, [])


# ── Endpoints affectations ──────────────────────────────────────────────────

@router.get("/assignments", response_model=List[AssignmentOut])
async def get_assignments(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> List[AssignmentOut]:
    care_units = list(
        (await db.execute(select(CareUnit).order_by(CareUnit.name))).scalars().all()
    )

    assignments = {
        a.care_unit_id: a
        for a in (await db.execute(select(QuestionnaireAssignment))).scalars().all()
    }

    questionnaires = {
        q.id: q
        for q in (await db.execute(select(Questionnaire))).scalars().all()
    }

    result: List[AssignmentOut] = []

    def _proche_fields(a: Optional[QuestionnaireAssignment]) -> tuple:
        if not a or not a.proche_questionnaire_id:
            return None, None
        pq = questionnaires.get(a.proche_questionnaire_id)
        return (str(pq.id) if pq else None), (pq.name if pq else None)

    # Ligne "Défaut"
    default_a = assignments.get(None)
    default_q = questionnaires.get(default_a.questionnaire_id) if default_a else None
    pq_id, pq_name = _proche_fields(default_a)
    result.append(
        AssignmentOut(
            care_unit_id=None,
            care_unit_name="Défaut",
            care_unit_code=None,
            questionnaire_id=str(default_q.id) if default_q else None,
            questionnaire_name=default_q.name if default_q else None,
            proche_questionnaire_id=pq_id,
            proche_questionnaire_name=pq_name,
            care_unit_active=None,
        )
    )

    # Une ligne par unité de soins (actives ou non — affectations toujours visibles)
    for cu in care_units:
        a = assignments.get(cu.id)
        q = questionnaires.get(a.questionnaire_id) if a else None
        pq_id, pq_name = _proche_fields(a)
        result.append(
            AssignmentOut(
                care_unit_id=str(cu.id),
                care_unit_name=cu.name,
                care_unit_code=cu.service_code,
                questionnaire_id=str(q.id) if q else None,
                questionnaire_name=q.name if q else None,
                proche_questionnaire_id=pq_id,
                proche_questionnaire_name=pq_name,
                care_unit_active=cu.is_active,
            )
        )

    return result


async def _upsert_assignment(
    db: AsyncSession,
    care_unit_id: Optional[UUID],
    questionnaire_id: UUID,
    *,
    do_commit: bool = True,
) -> None:
    q = await db.get(Questionnaire, questionnaire_id)
    if not q:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Questionnaire introuvable")
    if care_unit_id is None:
        existing = await db.scalar(
            select(QuestionnaireAssignment).where(
                QuestionnaireAssignment.care_unit_id.is_(None)
            )
        )
    else:
        existing = await db.scalar(
            select(QuestionnaireAssignment).where(
                QuestionnaireAssignment.care_unit_id == care_unit_id
            )
        )
    if existing:
        existing.questionnaire_id = questionnaire_id
    else:
        db.add(
            QuestionnaireAssignment(
                care_unit_id=care_unit_id,
                questionnaire_id=questionnaire_id,
            )
        )
    if do_commit:
        await db.commit()


@router.put("/assignments/default")
async def set_default_assignment(
    request: Request,
    body: QuestionnaireIdBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> Response:
    await _upsert_assignment(db, None, body.questionnaire_id)
    logger.info(f"[Admin] Questionnaire par défaut → {body.questionnaire_id}")
    await audit_service.log_action(
        db,
        action="admin_assignment_default",
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type="questionnaire_assignment",
        resource_id=body.questionnaire_id,
        details={"scope": "default"},
        request=request,
    )
    return Response(status_code=204)


@router.delete("/assignments/default")
async def remove_default_assignment(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> Response:
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        detail=(
            "L'affectation par défaut ne peut pas être supprimée — "
            "elle garantit qu'un questionnaire est toujours disponible lors des appels. "
            "Pour la changer, utilisez PUT /assignments/default."
        ),
    )


@router.put("/assignments/{care_unit_id}")
async def set_care_unit_assignment(
    request: Request,
    care_unit_id: UUID,
    body: QuestionnaireIdBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> Response:
    cu = await db.get(CareUnit, care_unit_id)
    if not cu:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unité de soins introuvable")
    await _upsert_assignment(db, care_unit_id, body.questionnaire_id)
    logger.info(f"[Admin] {cu.name} → questionnaire {body.questionnaire_id}")
    await audit_service.log_action(
        db,
        action="admin_assignment_care_unit",
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type="questionnaire_assignment",
        resource_id=body.questionnaire_id,
        resource_name=cu.name,
        details={"care_unit_id": str(care_unit_id)},
        request=request,
    )
    return Response(status_code=204)


@router.delete("/assignments/{care_unit_id}")
async def remove_care_unit_assignment(
    request: Request,
    care_unit_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> Response:
    existing = await db.scalar(
        select(QuestionnaireAssignment).where(
            QuestionnaireAssignment.care_unit_id == care_unit_id
        )
    )
    if existing:
        await db.delete(existing)
        await db.commit()
        await audit_service.log_action(
            db,
            action="admin_assignment_care_unit_clear",
            user_id=current_user.id,
            user_email=current_user.email,
            resource_type="questionnaire_assignment",
            details={"care_unit_id": str(care_unit_id)},
            request=request,
        )
    return Response(status_code=204)


# ── Endpoints affectations — proche ────────────────────────────────────────


async def _upsert_proche(
    db: AsyncSession,
    care_unit_id: Optional[UUID],
    proche_questionnaire_id: Optional[UUID],
    *,
    do_commit: bool = True,
) -> None:
    """Met à jour proche_questionnaire_id sur l'assignment existant (NULL = effacer)."""
    if care_unit_id is None:
        assignment = await db.scalar(
            select(QuestionnaireAssignment).where(QuestionnaireAssignment.care_unit_id.is_(None))
        )
    else:
        assignment = await db.scalar(
            select(QuestionnaireAssignment).where(
                QuestionnaireAssignment.care_unit_id == care_unit_id
            )
        )
    if not assignment:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Aucune affectation trouvée pour ce service — assignez d'abord un questionnaire patient.",
        )
    if proche_questionnaire_id is not None:
        q = await db.get(Questionnaire, proche_questionnaire_id)
        if not q:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Questionnaire proche introuvable")
    assignment.proche_questionnaire_id = proche_questionnaire_id
    if do_commit:
        await db.commit()


@router.put("/assignments/default/proche")
async def set_default_proche_assignment(
    request: Request,
    body: QuestionnaireIdBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> Response:
    await _upsert_proche(db, None, body.questionnaire_id)
    logger.info(f"[Admin] Questionnaire proche par défaut → {body.questionnaire_id}")
    await audit_service.log_action(
        db,
        action="admin_assignment_proche_default",
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type="questionnaire_assignment",
        resource_id=body.questionnaire_id,
        details={"scope": "default", "role": "proche"},
        request=request,
    )
    return Response(status_code=204)


@router.delete("/assignments/default/proche")
async def clear_default_proche_assignment(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> Response:
    await _upsert_proche(db, None, None)
    logger.info("[Admin] Questionnaire proche par défaut effacé — fallback sur questionnaire patient")
    await audit_service.log_action(
        db,
        action="admin_assignment_proche_default_clear",
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type="questionnaire_assignment",
        details={"scope": "default", "role": "proche"},
        request=request,
    )
    return Response(status_code=204)


@router.put("/assignments/{care_unit_id}/proche")
async def set_care_unit_proche_assignment(
    request: Request,
    care_unit_id: UUID,
    body: QuestionnaireIdBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> Response:
    cu = await db.get(CareUnit, care_unit_id)
    if not cu:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unité de soins introuvable")
    await _upsert_proche(db, care_unit_id, body.questionnaire_id)
    logger.info(f"[Admin] {cu.name} → questionnaire proche {body.questionnaire_id}")
    await audit_service.log_action(
        db,
        action="admin_assignment_proche_care_unit",
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type="questionnaire_assignment",
        resource_id=body.questionnaire_id,
        resource_name=cu.name,
        details={"care_unit_id": str(care_unit_id), "role": "proche"},
        request=request,
    )
    return Response(status_code=204)


@router.delete("/assignments/{care_unit_id}/proche")
async def clear_care_unit_proche_assignment(
    request: Request,
    care_unit_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> Response:
    cu = await db.get(CareUnit, care_unit_id)
    if not cu:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unité de soins introuvable")
    await _upsert_proche(db, care_unit_id, None)
    logger.info(f"[Admin] {cu.name} — questionnaire proche effacé (fallback sur questionnaire patient)")
    await audit_service.log_action(
        db,
        action="admin_assignment_proche_care_unit_clear",
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type="questionnaire_assignment",
        resource_name=cu.name,
        details={"care_unit_id": str(care_unit_id), "role": "proche"},
        request=request,
    )
    return Response(status_code=204)


class BulkAssignPayload(BaseModel):
    questionnaire_id: str
    care_unit_ids: Optional[List[str]] = None  # None ou absent = tous les services actifs
    include_default: bool = False


@router.post("/assignments/bulk")
async def bulk_assign(
    request: Request,
    payload: BulkAssignPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> Response:
    q_id = UUID(payload.questionnaire_id)
    q = await db.get(Questionnaire, q_id)
    if not q:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Questionnaire introuvable")

    if payload.care_unit_ids is None:
        care_units = list(
            (await db.execute(select(CareUnit).where(CareUnit.is_active.is_(True)))).scalars().all()
        )
        ids = [cu.id for cu in care_units]
    else:
        ids = [UUID(x) for x in payload.care_unit_ids]

    for cu_id in ids:
        await _upsert_assignment(db, cu_id, q_id, do_commit=False)

    if payload.include_default:
        await _upsert_assignment(db, None, q_id, do_commit=False)

    await db.commit()
    logger.info(f"[Admin] Affectation en masse : {len(ids)} service(s) → {q.name!r}")
    await audit_service.log_action(
        db,
        action="admin_assignment_bulk",
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type="questionnaire",
        resource_id=q_id,
        resource_name=q.name,
        details={
            "care_units": len(ids),
            "include_default": payload.include_default,
        },
        request=request,
    )
    return Response(status_code=204)


# ── Paramètres d'appel (inchangés) ─────────────────────────────────────────

@router.get("/call-settings", response_model=CallSettingsPayload)
async def get_call_settings(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user),
) -> CallSettingsPayload:
    stored = await _get_setting(db, _KEY_CALL_SETTINGS)
    if stored and isinstance(stored, dict):
        return CallSettingsPayload.model_validate(stored)
    return CallSettingsPayload()


@router.put("/call-settings", response_model=CallSettingsPayload)
async def save_call_settings(
    request: Request,
    payload: CallSettingsPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> CallSettingsPayload:
    if payload.call_window_start >= payload.call_window_end:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="L'heure de début doit être antérieure à l'heure de fin.",
        )
    if not payload.allowed_days:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Au moins un jour autorisé est requis.",
        )
    await _set_setting(db, _KEY_CALL_SETTINGS, payload.model_dump())
    logger.info("[Admin] Paramètres d'appel mis à jour")
    # Invalider le cache mémoire pour que les prochains appels utilisent les nouvelles valeurs
    from app.services.call_settings_service import call_settings_service
    call_settings_service.invalidate()
    await audit_service.log_action(
        db,
        action="admin_call_settings_update",
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type="call_settings",
        resource_name=_KEY_CALL_SETTINGS,
        request=request,
    )
    return payload
