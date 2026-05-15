"""Add follow-up questions fields to questions table

Revision ID: 009_add_followup_fields
Revises: 008_add_question_type
Create Date: 2025-12-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '009_add_followup_fields'
down_revision: Union[str, None] = '008_add_question_type'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ajouter le champ is_follow_up
    op.add_column('questions', sa.Column(
        'is_follow_up',
        sa.Boolean(),
        nullable=False,
        server_default='false',
        comment="Si true, cette question est une sous-question d'une question principale"
    ))

    # Ajouter le champ parent_question_id
    op.add_column('questions', sa.Column(
        'parent_question_id',
        postgresql.UUID(as_uuid=True),
        nullable=True,
        comment="ID de la question principale si c'est une sous-question"
    ))

    # Créer un index pour is_follow_up
    op.create_index(op.f('ix_questions_is_follow_up'), 'questions', ['is_follow_up'])

    # Créer un index pour parent_question_id
    op.create_index(op.f('ix_questions_parent_question_id'), 'questions', ['parent_question_id'])

    # Créer la foreign key vers la table questions
    op.create_foreign_key(
        'fk_questions_parent_question_id',
        'questions',
        'questions',
        ['parent_question_id'],
        ['id'],
        ondelete='CASCADE'
    )


def downgrade() -> None:
    # Supprimer la foreign key
    op.drop_constraint('fk_questions_parent_question_id', 'questions', type_='foreignkey')

    # Supprimer les index
    op.drop_index(op.f('ix_questions_parent_question_id'), table_name='questions')
    op.drop_index(op.f('ix_questions_is_follow_up'), table_name='questions')

    # Supprimer les colonnes
    op.drop_column('questions', 'parent_question_id')
    op.drop_column('questions', 'is_follow_up')

