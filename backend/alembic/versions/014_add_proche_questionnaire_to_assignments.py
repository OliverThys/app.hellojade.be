"""Add proche_questionnaire_id to questionnaire_assignments

Revision ID: 014_add_proche_questionnaire
Revises: 013_add_manual_recall
Create Date: 2026-05-02

Ajoute une colonne nullable proche_questionnaire_id sur questionnaire_assignments.
Quand renseignée, le chargeur utilise ce questionnaire pour les appels où
caller_role == "proche" plutôt que le questionnaire patient.
ON DELETE SET NULL : si le questionnaire proche est supprimé, la colonne revient à NULL
(l'appel proche retombera alors sur le questionnaire patient).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014_add_proche_questionnaire"
down_revision: Union[str, None] = "013_add_manual_recall"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "questionnaire_assignments",
        sa.Column(
            "proche_questionnaire_id",
            sa.UUID(),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_qa_proche_questionnaire_id",
        "questionnaire_assignments",
        "questionnaires",
        ["proche_questionnaire_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_qa_proche_questionnaire_id", "questionnaire_assignments", type_="foreignkey")
    op.drop_column("questionnaire_assignments", "proche_questionnaire_id")
