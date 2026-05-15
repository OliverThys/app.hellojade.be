"""
Normalisation post-STT des noms de médicaments.

Après qu'Azure STT retourne du texte, ce module remplace les approximations
phonétiques ("voltarène", "ibuproféne") par les noms canoniques ("Voltaren",
"Ibuprofène").

Algorithme :
  1. Tokenisation du texte (mots + bigrammes pour les noms composés)
  2. Pour chaque token, fuzzy-match contre toutes les variantes connues
  3. Si score ≥ seuil, substitution par le nom canonique
  4. Reconstruction du texte

Dépendance : rapidfuzz (pip install rapidfuzz)
"""
from __future__ import annotations

import re
import unicodedata

from app.core.logging import get_logger
from app.services.ai.medication_vocabulary import medication_vocabulary, MedicationEntry

logger = get_logger(__name__)

_FUZZY_THRESHOLD = 82  # score minimum (0-100) pour valider un match
_MIN_TOKEN_LEN = 4     # ignorer les tokens trop courts (évite faux positifs)

try:
    from rapidfuzz import fuzz, process as fuzz_process
    _rapidfuzz_available = True
except ImportError:
    logger.warning("[MED_NORM] rapidfuzz non installé – normalisation désactivée")
    _rapidfuzz_available = False


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


def _build_variant_index(
    entries: list[MedicationEntry],
) -> tuple[list[str], list[str]]:
    """
    Retourne (variants_lower_no_accents, canonicals) en parallèle.
    variants[i] → canonicals[i]
    """
    variants: list[str] = []
    canonicals: list[str] = []
    for entry in entries:
        for v in entry.variants:
            variants.append(_strip_accents(v.lower()))
            canonicals.append(entry.canonical)
        # ajouter aussi les phrase_list_entries comme variantes
        for p in entry.phrase_list_entries:
            key = _strip_accents(p.lower())
            if key not in variants:
                variants.append(key)
                canonicals.append(entry.canonical)
    return variants, canonicals


def _get_index() -> tuple[list[str], list[str]]:
    entries = medication_vocabulary.get_all_entries()
    return _build_variant_index(entries)


def normalize_transcript(text: str) -> str:
    """
    Remplace dans `text` les approximations phonétiques de médicaments par
    leurs noms canoniques.

    Exemple :
        "j'ai pris du voltarène et de l'ibuproféne"
        → "j'ai pris du Voltaren et de l'Ibuprofène"

    Si rapidfuzz n'est pas installé, retourne `text` inchangé.
    """
    if not _rapidfuzz_available or not text:
        return text

    variants, canonicals = _get_index()
    if not variants:
        return text

    tokens = re.split(r"(\s+)", text)
    words = [t for t in tokens if t.strip()]
    separators = [t for t in tokens if not t.strip()]

    result_words: list[str] = []

    i = 0
    while i < len(words):
        # essai bigramme (noms composés : "acide acétylsalicylique")
        matched = False
        if i + 1 < len(words):
            bigram = words[i] + " " + words[i + 1]
            canonical, score = _fuzzy_match(bigram, variants, canonicals)
            if canonical and score >= _FUZZY_THRESHOLD:
                result_words.append(canonical)
                i += 2
                logger.debug(f"[MED_NORM] bigramme '{bigram}' → '{canonical}' (score {score})")
                matched = True

        if not matched:
            token = words[i]
            token_clean = _strip_accents(token.lower().strip(".,;:!?"))
            if len(token_clean) >= _MIN_TOKEN_LEN:
                canonical, score = _fuzzy_match(token_clean, variants, canonicals)
                if canonical and score >= _FUZZY_THRESHOLD:
                    result_words.append(canonical)
                    logger.debug(f"[MED_NORM] '{token}' → '{canonical}' (score {score})")
                    i += 1
                    matched = True

        if not matched:
            result_words.append(words[i])
            i += 1

    # reconstruction : entrelacement mots + espaces
    reconstructed_parts: list[str] = []
    for idx, word in enumerate(result_words):
        reconstructed_parts.append(word)
        if idx < len(separators):
            reconstructed_parts.append(separators[idx])

    normalized = "".join(reconstructed_parts).strip()
    if normalized != text:
        logger.info(f"[MED_NORM] Normalisation: '{text}' → '{normalized}'")
    return normalized


def _fuzzy_match(
    token: str,
    variants: list[str],
    canonicals: list[str],
) -> tuple[str | None, int]:
    """Retourne (canonical, score) ou (None, 0) si aucun match."""
    if not variants:
        return None, 0
    match = fuzz_process.extractOne(
        token,
        variants,
        scorer=fuzz.WRatio,
        score_cutoff=_FUZZY_THRESHOLD,
    )
    if match is None:
        return None, 0
    best_variant, score, idx = match
    return canonicals[idx], int(score)
