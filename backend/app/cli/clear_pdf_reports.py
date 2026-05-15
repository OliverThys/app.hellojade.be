"""
Supprime tous les rapports PDF ORU (table reports) et les fichiers associés.

  python -m app.cli.clear_pdf_reports
  python -m app.cli.clear_pdf_reports --dry-run

Dans Docker (après déploiement du code contenant app/cli) :
  docker exec -it hellojadeapp-backend python -m app.cli.clear_pdf_reports

Alternative SQL seule (PostgreSQL actif) :
  docker exec -it hellojadeapp-postgres psql -U hellojadeapp -d hellojadeapp -c "DELETE FROM reports;"
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.report import Report


async def run(*, dry_run: bool) -> None:
    engine = create_async_engine(str(settings.DATABASE_URL), echo=False)
    Session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    reports_dir = Path(settings.REPORTS_PATH)
    hl7_dir = reports_dir / "hl7"

    async with Session() as session:
        res = await session.execute(select(Report))
        rows = res.scalars().all()
        print(f"Rapports en base : {len(rows)}")

        for r in rows:
            p = Path(r.file_path)
            if p.is_file():
                print(f"  fichier : {p}")
                if not dry_run:
                    try:
                        p.unlink()
                    except OSError as e:
                        print(f"    (échec suppression fichier : {e})")

        if not dry_run:
            await session.execute(delete(Report))
            await session.commit()
            print("Table reports vidée.")
        else:
            print("[dry-run] aucune suppression en base.")

    for p in reports_dir.glob("rapport_*.pdf"):
        print(f"Orphelin : {p}")
        if not dry_run:
            try:
                p.unlink()
            except OSError as e:
                print(f"  (échec : {e})")

    if hl7_dir.is_dir():
        for p in hl7_dir.glob("*.hl7"):
            print(f"HL7 : {p}")
            if not dry_run:
                try:
                    p.unlink()
                except OSError as e:
                    print(f"  (échec : {e})")

    await engine.dispose()
    print("Terminé." if not dry_run else "Dry-run terminé.")


def main() -> None:
    p = argparse.ArgumentParser(description="Vider les rapports PDF ORU (BDD + fichiers)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
