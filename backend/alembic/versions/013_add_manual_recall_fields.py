"""Add manual recall fields to patients

Revision ID: 013_add_manual_recall
Revises: 012_fix_qa_uniques
Create Date: 2026-04-09

Ajoute 4 colonnes sur la table patients pour le workflow de rappel manuel :
- manually_recalled       : flag booléen (bloque les retries JADE)
- manually_recalled_at    : horodatage du rappel
- manually_recalled_by    : nom du soignant connecté (depuis IntraID)
- callback_note           : note rédigée par le soignant
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013_add_manual_recall"
down_revision: Union[str, None] = "012_fix_qa_uniques"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "patients",
        sa.Column(
            "manually_recalled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="True = rappelé manuellement, bloque les retries automatiques JADE",
        ),
    )
    op.add_column(
        "patients",
        sa.Column(
            "manually_recalled_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Horodatage du rappel manuel",
        ),
    )
    op.add_column(
        "patients",
        sa.Column(
            "manually_recalled_by",
            sa.String(200),
            nullable=True,
            comment="Nom du soignant qui a effectué le rappel (depuis IntraID)",
        ),
    )
    op.add_column(
        "patients",
        sa.Column(
            "callback_note",
            sa.Text(),
            nullable=True,
            comment="Note rédigée par le soignant lors du rappel manuel",
        ),
    )
    op.create_index(
        "ix_patients_manually_recalled",
        "patients",
        ["manually_recalled"],
    )


def downgrade() -> None:
    op.drop_index("ix_patients_manually_recalled", table_name="patients")
    op.drop_column("patients", "callback_note")
    op.drop_column("patients", "manually_recalled_by")
    op.drop_column("patients", "manually_recalled_at")
    op.drop_column("patients", "manually_recalled")
