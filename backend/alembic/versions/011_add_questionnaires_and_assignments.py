"""Add questionnaires and questionnaire_assignments tables

Revision ID: 011_add_questionnaires
Revises: 010_add_patient_documents
Create Date: 2026-04-06 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "011_add_questionnaires"
down_revision: Union[str, None] = "010_add_patient_documents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "questionnaires",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("questions", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("messages", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("is_factory_default", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    op.create_table(
        "questionnaire_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "care_unit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("care_units.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "questionnaire_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("questionnaires.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint("care_unit_id", name="uq_assignment_care_unit"),
    )
    op.create_index("ix_qassignment_care_unit", "questionnaire_assignments", ["care_unit_id"])


def downgrade() -> None:
    op.drop_table("questionnaire_assignments")
    op.drop_table("questionnaires")
