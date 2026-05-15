"""
Répare additional_info (condition_parent_id, conditions, etc.) depuis QUESTIONNAIRE.

Usage (depuis le dossier backend, avec .env chargé) :
  python scripts/repair_questionnaire_metadata.py

Docker :
  docker exec hellojadeapp-backend python /app/scripts/repair_questionnaire_metadata.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import AsyncSessionLocal
from app.services.telephony.questionnaire_metadata_repair import (
    repair_canonical_question_metadata,
)


async def main() -> None:
    async with AsyncSessionLocal() as db:
        n, details = await repair_canonical_question_metadata(db)
    print(json.dumps({"updated_questions": n, "details": details}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
