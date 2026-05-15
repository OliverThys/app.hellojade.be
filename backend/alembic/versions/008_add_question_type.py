"""Add question_type field to questions table

Revision ID: 008_add_question_type
Revises: 007_add_new_questionnaire_fields
Create Date: 2025-12-28 23:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '008_add_question_type'
down_revision: Union[str, None] = '007_add_new_questionnaire_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ajouter le champ question_type
    op.add_column('questions', sa.Column(
        'question_type',
        sa.String(20),
        nullable=False,
        server_default='question',
        comment="Type de question: 'intro', 'question', 'outro'"
    ))

    # Créer un index pour optimiser les requêtes par type
    op.create_index(op.f('ix_questions_question_type'), 'questions', ['question_type'])


def downgrade() -> None:
    # Supprimer l'index
    op.drop_index(op.f('ix_questions_question_type'), table_name='questions')

    # Supprimer la colonne
    op.drop_column('questions', 'question_type')
