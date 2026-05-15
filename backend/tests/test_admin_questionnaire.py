"""
Tests — API admin questionnaires / contrôle d'accès admin.
"""
import importlib.util
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4

from app.core.security import create_access_token, get_password_hash
from app.models.user import User


def _load_demo_questionnaire_payload() -> dict:
    """Même JSON que scripts/create_questionnaire_via_api.py (routes HTTP réelles)."""
    script = Path(__file__).resolve().parent.parent / "scripts" / "create_questionnaire_via_api.py"
    spec = importlib.util.spec_from_file_location("create_questionnaire_via_api", script)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return dict(mod.DEMO_QUESTIONNAIRE)


@pytest.mark.asyncio
@pytest.mark.unit
class TestAdminQuestionnaireAccess:
    async def test_non_admin_forbidden(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        op = User(
            id=uuid4(),
            email="operateur_admin_test@example.com",
            username="op_adm_q",
            full_name="Op Test",
            hashed_password=get_password_hash("secret123"),
            role="operateur",
            is_active=True,
        )
        db_session.add(op)
        await db_session.commit()

        token = create_access_token(
            subject=op.id,
            additional_claims={"role": op.role, "email": op.email},
        )
        r = await async_client.get(
            "/api/v1/admin/questionnaires",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403

    async def test_admin_ok(
        self,
        async_client: AsyncClient,
        admin_token: str,
    ) -> None:
        r = await async_client.get(
            "/api/v1/admin/questionnaires",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_admin_create_demo_questionnaire_via_post(
        self,
        async_client: AsyncClient,
        admin_token: str,
    ) -> None:
        """Exécute le même flux que le script create_questionnaire_via_api.py."""
        payload = _load_demo_questionnaire_payload()
        r = await async_client.post(
            "/api/v1/admin/questionnaires",
            headers={"Authorization": f"Bearer {admin_token}"},
            json=payload,
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["name"] == payload["name"]
        assert len(data["questions"]) == len(payload["questions"])
        assert data["is_factory_default"] is False


def test_dto_to_call_format_sorts_by_order() -> None:
    from app.services.telephony.questionnaire_loader import _dto_to_call_format

    data = [
        {
            "question_id": "second",
            "text": "Deux",
            "order": 2,
            "is_active": True,
            "type": "yesno",
            "follow_ups": [],
        },
        {
            "question_id": "first",
            "text": "Un",
            "order": 1,
            "is_active": True,
            "type": "yesno",
            "follow_ups": [],
        },
    ]
    out = _dto_to_call_format(data)
    assert [x["id"] for x in out] == ["first", "second"]
