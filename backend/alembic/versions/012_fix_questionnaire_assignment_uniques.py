"""Fix questionnaire_assignments: partial uniques (one default, one per service)

Revision ID: 012_fix_qa_uniques
Revises: 011_add_questionnaires
Create Date: 2026-04-06

PostgreSQL UNIQUE(care_unit_id) allows multiple NULLs. Replace with:
- unique (care_unit_id) WHERE care_unit_id IS NOT NULL
- unique singleton for default: ((1)) WHERE care_unit_id IS NULL
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012_fix_qa_uniques"
down_revision: Union[str, None] = "011_add_questionnaires"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Dédupliquer les affectations « défaut » (plusieurs NULL possibles avant correctif)
    defaults = conn.execute(
        sa.text(
            "SELECT id FROM questionnaire_assignments "
            "WHERE care_unit_id IS NULL ORDER BY assigned_at DESC NULLS LAST, id DESC"
        )
    ).fetchall()
    if len(defaults) > 1:
        keep_id = defaults[0][0]
        for row in defaults[1:]:
            conn.execute(
                sa.text("DELETE FROM questionnaire_assignments WHERE id = :id"),
                {"id": row[0]},
            )

    # Dédupliquer par care_unit_id non NULL (au cas où données incohérentes)
    by_cu: dict = {}
    for rid, cu in conn.execute(
        sa.text(
            "SELECT id, care_unit_id FROM questionnaire_assignments "
            "WHERE care_unit_id IS NOT NULL ORDER BY assigned_at DESC NULLS LAST, id DESC"
        )
    ):
        if cu not in by_cu:
            by_cu[cu] = rid
        else:
            conn.execute(
                sa.text("DELETE FROM questionnaire_assignments WHERE id = :id"),
                {"id": rid},
            )

    op.drop_constraint("uq_assignment_care_unit", "questionnaire_assignments", type_="unique")
    op.create_index(
        "uq_qa_care_unit_id_when_set",
        "questionnaire_assignments",
        ["care_unit_id"],
        unique=True,
        postgresql_where=sa.text("care_unit_id IS NOT NULL"),
    )
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_qa_singleton_default ON questionnaire_assignments ((1)) "
            "WHERE care_unit_id IS NULL"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS uq_qa_singleton_default"))
    op.drop_index("uq_qa_care_unit_id_when_set", table_name="questionnaire_assignments")
    op.create_unique_constraint(
        "uq_assignment_care_unit",
        "questionnaire_assignments",
        ["care_unit_id"],
    )
