"""
Charge le questionnaire actif pour un appel donné.

Priorité :
  1. QuestionnaireAssignment pour le service du patient (care_unit.service_code)
  2. QuestionnaireAssignment par défaut (care_unit_id IS NULL)
  3. Questionnaire hardcodé dans questionnaire.py (dernier recours)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.care_unit import CareUnit
from app.models.questionnaire import Questionnaire, QuestionnaireAssignment

from .questionnaire import QUESTIONNAIRE, RECORD_DURATION_LONG, RECORD_DURATION_SHORT

# Index {question_id: question_proche} et {fu_id: question_proche} depuis le fallback Python
# Permet d'hériter des variantes proches sur les questionnaires chargés depuis la DB.
_PYTHON_Q_PROCHE: Dict[str, str] = {}
_PYTHON_FU_PROCHE: Dict[str, str] = {}

def _build_proche_index() -> None:
    for q in QUESTIONNAIRE:
        if q.get("question_proche"):
            _PYTHON_Q_PROCHE[q["id"]] = q["question_proche"]
        for fu in q.get("follow_ups", []):
            if fu.get("question_proche"):
                _PYTHON_FU_PROCHE[fu["id"]] = fu["question_proche"]

_build_proche_index()

logger = get_logger(__name__)


def _dto_to_call_format(questions_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convertit le format DTOMainQuestionDTO (stocké en JSONB) vers le format
    runtime attendu par asterisk_ari_service (clé 'question' au lieu de 'text', etc.).
    """
    sorted_data = sorted(
        questions_data,
        key=lambda x: (x.get("order") is None, x.get("order", 0)),
    )
    out: List[Dict[str, Any]] = []
    for q in sorted_data:
        if not q.get("is_active", True):
            continue

        qid_raw = q.get("question_id")
        qtext_raw = q.get("text")
        if not qid_raw or qtext_raw is None or (isinstance(qtext_raw, str) and not qtext_raw.strip()):
            logger.warning(
                "[QuestionnaireLoader] Question ignorée (question_id ou text manquant): %s",
                q,
            )
            continue

        qtype = q.get("type", "yesno")
        duration = int(q.get("record_duration") or 0)
        if duration <= 0:
            duration = 30 if qtype == "yesno" else 60

        q_proche = q.get("text_proche") or _PYTHON_Q_PROCHE.get(qid_raw, "")
        main: Dict[str, Any] = {
            "id": qid_raw,
            "question": qtext_raw,
            "type": qtype,
            "record_duration": min(duration, 120),
            "follow_ups": [],
        }
        if q_proche:
            main["question_proche"] = q_proche
        if q.get("alert_if") is not None:
            main["alert_if"] = q["alert_if"]
        if q.get("alert_if_gte") is not None:
            main["alert_if_gte"] = q["alert_if_gte"]
        if q.get("alert_type", "clinical") != "clinical":
            main["alert_type"] = q["alert_type"]
        if q.get("choices"):
            main["choices"] = q["choices"]
        if q.get("medication_context"):
            main["medication_context"] = True

        for fu in q.get("follow_ups", []):
            if not fu.get("is_active", True):
                continue
            fu_id = fu.get("question_id")
            fu_text = fu.get("text")
            if not fu_id or fu_text is None or (isinstance(fu_text, str) and not fu_text.strip()):
                logger.warning(
                    "[QuestionnaireLoader] Sous-question ignorée (champs manquants), parent %s",
                    qid_raw,
                )
                continue
            fu_type = fu.get("type", "yesno")
            fu_dur = int(fu.get("record_duration") or 0)
            if fu_dur <= 0:
                fu_dur = RECORD_DURATION_LONG if fu_type == "open" else RECORD_DURATION_SHORT

            fu_proche = fu.get("text_proche") or _PYTHON_FU_PROCHE.get(fu_id, "")
            fu_out: Dict[str, Any] = {
                "id": fu_id,
                "question": fu_text,
                "type": fu_type,
                "record_duration": min(fu_dur, 120),
            }
            if fu_proche:
                fu_out["question_proche"] = fu_proche
            if fu.get("condition") is not None:
                fu_out["condition"] = fu["condition"]
            if fu.get("condition_parent_id"):
                fu_out["condition_parent_id"] = fu["condition_parent_id"]
            if fu.get("alert_if") is not None:
                fu_out["alert_if"] = fu["alert_if"]
            if fu.get("alert_if_gte") is not None:
                fu_out["alert_if_gte"] = fu["alert_if_gte"]
            if fu.get("alert_type", "clinical") != "clinical":
                fu_out["alert_type"] = fu["alert_type"]
            if fu.get("choices"):
                fu_out["choices"] = fu["choices"]
            if fu.get("optional"):
                fu_out["optional"] = True
            main["follow_ups"].append(fu_out)

        out.append(main)

    return out


async def load_questionnaire_for_service(
    db: AsyncSession,
    service_code: Optional[str] = None,
    caller_role: str = "patient",
) -> List[Dict[str, Any]]:
    """
    Charge le questionnaire actif pour un service donné.

    caller_role : "patient" (défaut) ou "proche".
      - "proche" → utilise proche_questionnaire_id sur l'assignment si défini,
        sinon retombe sur le questionnaire patient du même service.
    service_code : valeur de patient.service_hospitalisation (= PV1.3 de l'ADT).
    """
    assignment: Optional[QuestionnaireAssignment] = None

    # 1. Chercher l'assignment par service_code
    if service_code:
        cu = await db.scalar(
            select(CareUnit).where(
                CareUnit.service_code == service_code,
                CareUnit.is_active.is_(True),
            )
        )
        if cu:
            assignment = await db.scalar(
                select(QuestionnaireAssignment).where(
                    QuestionnaireAssignment.care_unit_id == cu.id
                )
            )

    # 2. Fallback : assignment par défaut
    if not assignment:
        assignment = await db.scalar(
            select(QuestionnaireAssignment).where(
                QuestionnaireAssignment.care_unit_id.is_(None)
            )
        )

    if not assignment:
        logger.warning(
            "[QuestionnaireLoader] Aucun questionnaire assigné en base — utilisation du fallback Python"
        )
        return QUESTIONNAIRE

    # 3. Choisir l'ID questionnaire selon le rôle
    q_id = assignment.questionnaire_id
    role_label = "patient"
    if caller_role == "proche" and assignment.proche_questionnaire_id:
        q_id = assignment.proche_questionnaire_id
        role_label = "proche"

    questionnaire_row = await db.get(Questionnaire, q_id)

    # 4. Fallback vers questionnaire patient si le proche est absent/introuvable
    if not questionnaire_row and caller_role == "proche":
        logger.warning(
            "[QuestionnaireLoader] Questionnaire proche introuvable — retour au questionnaire patient"
        )
        questionnaire_row = await db.get(Questionnaire, assignment.questionnaire_id)
        role_label = "patient (fallback)"

    if not questionnaire_row:
        logger.warning(
            "[QuestionnaireLoader] Aucun questionnaire trouvé en base — utilisation du fallback Python"
        )
        return QUESTIONNAIRE

    logger.info(
        f"[QuestionnaireLoader] Service='{service_code or 'défaut'}' role={caller_role} → "
        f"questionnaire '{questionnaire_row.name}' [{role_label}]"
    )

    questions_data = questionnaire_row.questions or []
    if not questions_data:
        logger.error(
            f"[QuestionnaireLoader] Questionnaire '{questionnaire_row.name}' n'a aucune question — "
            "vérifiez la configuration admin."
        )
        return []

    result = _dto_to_call_format(questions_data)
    logger.info(
        f"[QuestionnaireLoader] {len(result)} question(s) principale(s) chargée(s) "
        f"(questionnaire '{questionnaire_row.name}')"
    )
    return result


async def load_messages_for_service(
    db: AsyncSession,
    service_code: Optional[str] = None,
    caller_role: str = "patient",
) -> Dict[str, str]:
    """
    Charge les messages (welcome, outro_*) du questionnaire actif pour un service.
    caller_role : "patient" ou "proche" — utilise le questionnaire correspondant.
    """
    from app.services.telephony.questionnaire import (
        WELCOME_MESSAGE,
        CLOSING_MESSAGE_NORMAL,
        CLOSING_MESSAGE_ALERT,
        CLOSING_MESSAGE_TRANSFER_FAILED,
    )

    defaults = {
        "welcome": WELCOME_MESSAGE,
        "outro_normal": CLOSING_MESSAGE_NORMAL,
        "outro_alert": CLOSING_MESSAGE_ALERT,
        "outro_transfer_failed": CLOSING_MESSAGE_TRANSFER_FAILED,
    }

    # Résoudre l'assignment
    assignment: Optional[QuestionnaireAssignment] = None
    if service_code:
        cu = await db.scalar(
            select(CareUnit).where(
                CareUnit.service_code == service_code,
                CareUnit.is_active.is_(True),
            )
        )
        if cu:
            assignment = await db.scalar(
                select(QuestionnaireAssignment).where(
                    QuestionnaireAssignment.care_unit_id == cu.id
                )
            )
    if not assignment:
        assignment = await db.scalar(
            select(QuestionnaireAssignment).where(
                QuestionnaireAssignment.care_unit_id.is_(None)
            )
        )

    if not assignment:
        return defaults

    # Choisir le questionnaire selon le rôle
    q_id = assignment.questionnaire_id
    if caller_role == "proche" and assignment.proche_questionnaire_id:
        q_id = assignment.proche_questionnaire_id

    questionnaire_row = await db.get(Questionnaire, q_id)
    if caller_role == "proche" and (not questionnaire_row or not questionnaire_row.messages):
        # Fallback sur questionnaire patient
        questionnaire_row = await db.get(Questionnaire, assignment.questionnaire_id)

    if not questionnaire_row or not questionnaire_row.messages:
        return defaults

    msgs = questionnaire_row.messages
    return {
        "welcome": msgs.get("welcome") or defaults["welcome"],
        "outro_normal": msgs.get("outro_normal") or defaults["outro_normal"],
        "outro_alert": msgs.get("outro_alert") or defaults["outro_alert"],
        "outro_transfer_failed": msgs.get("outro_transfer_failed") or defaults["outro_transfer_failed"],
    }


# Compat : ancienne signature utilisée dans le code existant
async def load_active_questionnaire_for_calls(db: AsyncSession) -> List[Dict[str, Any]]:
    return await load_questionnaire_for_service(db, service_code=None)
