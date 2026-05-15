"""
Réparation non destructive des champs `additional_info` des questions
à partir du questionnaire canonique Python (QUESTIONNAIRE).

Utile après une sync V2 ancienne sans `condition_parent_id` sur les sous-questions.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.question import Question

from .questionnaire import QUESTIONNAIRE

logger = get_logger(__name__)


def _json_equal(a: Any, b: Any) -> bool:
    try:
        return json.dumps(a, sort_keys=True, default=str) == json.dumps(
            b, sort_keys=True, default=str
        )
    except (TypeError, ValueError):
        return a == b


def _patch_from_main_question(q_data: Dict[str, Any]) -> Dict[str, Any]:
    p: Dict[str, Any] = {
        "response_type": q_data.get("type", "yesno"),
        "timeout": q_data.get("timeout", 10),
    }
    for key in ("alert_if", "alert_conditions", "choices"):
        if key in q_data:
            p[key] = q_data[key]
    return p


def _patch_from_follow_up(fu_data: Dict[str, Any]) -> Dict[str, Any]:
    p: Dict[str, Any] = {
        "response_type": fu_data.get("type", "yesno"),
        "timeout": fu_data.get("timeout", 10),
        "optional": fu_data.get("optional", False),
    }
    for key in (
        "condition",
        "condition_parent_id",
        "alert_if",
        "alert_if_value",
        "choices",
    ):
        if key in fu_data:
            p[key] = fu_data[key]
    return p


def _build_expected_patches_by_question_id() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for q_data in QUESTIONNAIRE:
        out[q_data["id"]] = _patch_from_main_question(q_data)
        for fu in q_data.get("follow_ups", []):
            out[fu["id"]] = _patch_from_follow_up(fu)
    return out


async def repair_canonical_question_metadata(
    db: AsyncSession,
) -> Tuple[int, List[Dict[str, Any]]]:
    """
    Met à jour `additional_info` pour chaque ligne dont `question_id` correspond
    au questionnaire canonique, sans supprimer de lignes ni toucher aux textes.

    Returns:
        (nombre de lignes modifiées, détail des changements)
    """
    expected = _build_expected_patches_by_question_id()
    if not expected:
        return 0, []

    result = await db.execute(select(Question))
    rows = list(result.scalars().all())

    updated_count = 0
    details: List[Dict[str, Any]] = []

    for row in rows:
        qid = row.question_id
        patch = expected.get(qid)
        if not patch:
            continue

        base = dict(row.additional_info) if isinstance(row.additional_info, dict) else {}
        merged = dict(base)
        changed_keys: List[str] = []

        for key, value in patch.items():
            if key not in merged or not _json_equal(merged.get(key), value):
                merged[key] = value
                changed_keys.append(key)

        if not changed_keys:
            continue

        row.additional_info = merged
        updated_count += 1
        details.append(
            {
                "question_id": qid,
                "uuid": str(row.id),
                "keys_updated": changed_keys,
            }
        )
        logger.info(f"[MetadataRepair] {qid}: mis à jour {changed_keys}")

    if updated_count:
        await db.commit()

    return updated_count, details
