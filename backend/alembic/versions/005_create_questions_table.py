"""Create questions table with additional_info field

Revision ID: 005_create_questions_table
Revises: 004_add_interrupted_status
Create Date: 2025-01-20 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '005_create_questions_table'
down_revision: Union[str, None] = '004_add_interrupted_status'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Créer la table questions
    op.create_table(
        'questions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('question_id', sa.String(100), nullable=False, unique=True),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('max_duration', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('additional_info', postgresql.JSONB(astext_type=sa.Text()), nullable=True, default=dict),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    
    # Créer les index
    op.create_index(op.f('ix_questions_question_id'), 'questions', ['question_id'], unique=True)
    op.create_index(op.f('ix_questions_order'), 'questions', ['order'])


def downgrade() -> None:
    # Supprimer les index
    op.drop_index(op.f('ix_questions_order'), table_name='questions')
    op.drop_index(op.f('ix_questions_question_id'), table_name='questions')
    
    # Supprimer la table
    op.drop_table('questions')

