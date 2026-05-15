"""
Vocabulaire médicaments pour l'amélioration du STT Azure.

Charge les listes de médicaments (antidouleurs + anti-inflammatoires) au
démarrage et expose :
  - get_phrase_list_entries() → injectées dans Azure PhraseListGrammar
  - get_all_entries()         → utilisées par le normalizer pour fuzzy-match
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

from app.core.logging import get_logger

logger = get_logger(__name__)

_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "medications"


class MedicationEntry(NamedTuple):
    canonical: str
    dci: str
    category: str
    phrase_list_entries: list[str]
    variants: list[str]


class MedicationVocabulary:
    """
    Singleton chargé une fois à l'import.

    Usage:
        from app.services.ai.medication_vocabulary import medication_vocabulary
        entries = medication_vocabulary.get_all_entries()
        phrases = medication_vocabulary.get_phrase_list_entries()
    """

    def __init__(self) -> None:
        self._entries: list[MedicationEntry] = []
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        files = [
            _DATA_DIR / "antidouleurs.json",
            _DATA_DIR / "anti_inflammatoires.json",
        ]
        for path in files:
            if not path.exists():
                logger.warning(f"[MED_VOCAB] Fichier manquant : {path}")
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                for item in data:
                    self._entries.append(
                        MedicationEntry(
                            canonical=item["canonical"],
                            dci=item.get("dci", ""),
                            category=item.get("category", ""),
                            phrase_list_entries=item.get("phrase_list_entries", []),
                            variants=item.get("variants", []),
                        )
                    )
            except Exception as exc:
                logger.error(f"[MED_VOCAB] Erreur chargement {path}: {exc}")

        self._loaded = True
        logger.info(
            f"[MED_VOCAB] {len(self._entries)} médicaments chargés "
            f"depuis {len(files)} fichiers"
        )

    def get_all_entries(self) -> list[MedicationEntry]:
        self._load()
        return self._entries

    def get_phrase_list_entries(self) -> list[str]:
        """
        Retourne toutes les chaînes à injecter dans Azure PhraseListGrammar.
        Limite Azure : ~500 phrases. On reste bien en dessous.
        """
        self._load()
        seen: set[str] = set()
        result: list[str] = []
        for entry in self._entries:
            for phrase in entry.phrase_list_entries:
                normalized = phrase.strip()
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    result.append(normalized)
        return result

    def get_canonical_names(self) -> list[str]:
        self._load()
        return [e.canonical for e in self._entries]


medication_vocabulary = MedicationVocabulary()
