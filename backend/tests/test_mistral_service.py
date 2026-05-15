"""
Tests unitaires : hors périmètre (out_of_scope), normalisation et parseur de secours.
"""
from unittest.mock import PropertyMock, patch

import pytest

from app.services.ai.mistral_service import (
    MistralService,
    _fallback_parse,
    parsed_is_out_of_scope,
)


@pytest.mark.unit
class TestParsedIsOutOfScope:
    """Détection hors périmètre depuis le JSON LLM (bool, chaînes, notes)."""

    def test_true_bool(self) -> None:
        assert parsed_is_out_of_scope({"out_of_scope": True}) is True

    def test_false_bool(self) -> None:
        assert parsed_is_out_of_scope({"out_of_scope": False}) is False

    def test_string_true_variants(self) -> None:
        for s in ("true", "TRUE", " True ", "1", "yes", "oui"):
            assert parsed_is_out_of_scope({"out_of_scope": s}) is True

    def test_string_other(self) -> None:
        assert parsed_is_out_of_scope({"out_of_scope": "false"}) is False

    def test_notes_exact_token(self) -> None:
        assert parsed_is_out_of_scope({"notes": "out_of_scope"}) is True
        assert parsed_is_out_of_scope({"notes": "OUT_OF_SCOPE"}) is True
        assert parsed_is_out_of_scope({"notes": "out-of-scope"}) is True
        assert parsed_is_out_of_scope({"notes": "out of scope"}) is True

    def test_notes_other(self) -> None:
        assert parsed_is_out_of_scope({"notes": "hors sujet"}) is False
        assert parsed_is_out_of_scope({"notes": None}) is False


@pytest.mark.unit
class TestNormalizeParsedResponse:
    """Comportement après parsing : answer vide si OOB, understood forcé."""

    def test_out_of_scope_true_clears_answer_and_understood_true(self) -> None:
        raw = {
            "answer": "non",
            "confidence": 0.9,
            "understood": False,
            "out_of_scope": True,
            "notes": None,
        }
        out = MistralService.normalize_parsed_response(raw)
        assert out["out_of_scope"] is True
        assert out["understood"] is True
        assert out["answer"] == ""

    def test_string_out_of_scope_normalized_to_bool(self) -> None:
        raw = {
            "answer": "",
            "confidence": 0.8,
            "understood": True,
            "out_of_scope": "oui",
            "notes": None,
        }
        out = MistralService.normalize_parsed_response(raw)
        assert out["out_of_scope"] is True
        assert out["answer"] == ""

    def test_notes_free_text_with_out_scope_sets_flag(self) -> None:
        raw = {
            "answer": "non",
            "confidence": 0.5,
            "understood": True,
            "notes": "Patient is clearly out of scope here",
        }
        out = MistralService.normalize_parsed_response(raw)
        assert out["notes"] == "out_of_scope"
        assert out["out_of_scope"] is True
        assert out["answer"] == ""

    def test_in_scope_yesno_unchanged(self) -> None:
        raw = {
            "answer": "oui",
            "confidence": 0.95,
            "understood": True,
            "out_of_scope": False,
            "notes": None,
        }
        out = MistralService.normalize_parsed_response(raw)
        assert out["out_of_scope"] is False
        assert out["answer"] == "oui"


@pytest.mark.unit
class TestFallbackParse:
    """Parseur regex : toujours une clé out_of_scope explicite."""

    def test_empty_has_out_of_scope_false(self) -> None:
        r = _fallback_parse("", "yesno")
        assert r["out_of_scope"] is False
        assert r["understood"] is False

    def test_yesno_detected(self) -> None:
        r = _fallback_parse("ouais", "yesno")
        assert r["out_of_scope"] is False
        assert r["answer"] == "oui"
        r2 = _fallback_parse("pas du tout", "yesno")
        assert r2["out_of_scope"] is False
        assert r2["answer"] == "non"

    def test_ambiguous_yesno_still_has_out_of_scope_false(self) -> None:
        r = _fallback_parse("les pâtes", "yesno")
        assert r["out_of_scope"] is False
        assert "answer" in r

    def test_yesno_strip_trailing_politeness(self) -> None:
        r = _fallback_parse("non pas de douleur, bien compris", "yesno")
        assert r["out_of_scope"] is False
        assert r["answer"] == "non"
        assert r["understood"] is True

    def test_yesno_only_politeness_understood_false(self) -> None:
        r = _fallback_parse("bien compris", "yesno")
        assert r["out_of_scope"] is False
        assert r["understood"] is False


@pytest.mark.unit
class TestAnalyzeResponseEmpty:
    """Réponse STT vide : pas d'appel réseau, structure complète."""

    @pytest.mark.asyncio
    async def test_whitespace_only_returns_out_of_scope_false(self) -> None:
        svc = MistralService()
        result = await svc.analyze_response(
            "Q1_douleur",
            "Avez-vous mal ?",
            "yesno",
            "   \n\t  ",
        )
        assert result["understood"] is False
        assert result["out_of_scope"] is False
        assert result["answer"] == ""


@pytest.mark.unit
class TestAnalyzeResponseFallbackNoLlm:
    """Forcer l'absence de LLM : le parseur de secours est utilisé (déterministe)."""

    @pytest.mark.asyncio
    async def test_yesno_via_fallback(self) -> None:
        with (
            patch.object(
                MistralService,
                "mistral_available",
                PropertyMock(return_value=False),
            ),
            patch.object(
                MistralService,
                "azure_openai_available",
                PropertyMock(return_value=False),
            ),
        ):
            svc = MistralService()
            result = await svc.analyze_response(
                "Q1_douleur",
                "Avez-vous mal ?",
                "yesno",
                "oui madame",
            )
        assert result["out_of_scope"] is False
        assert result["answer"] == "oui"
