"""Add phone_invalid fields to patients table

Revision ID: 006_add_phone_invalid_fields
Revises: 005_create_questions_table
Create Date: 2025-01-20 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '006_add_phone_invalid_fields'
down_revision: Union[str, None] = '005_create_questions_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ajouter les colonnes pour la gestion des numéros invalides
    op.add_column('patients', sa.Column('phone_invalid', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('patients', sa.Column('phone_invalid_reason', sa.String(200), nullable=True))
    op.add_column('patients', sa.Column('phone_invalid_at', sa.DateTime(timezone=True), nullable=True))
    
    # Créer un index sur phone_invalid pour les requêtes de filtrage
    op.create_index(op.f('ix_patients_phone_invalid'), 'patients', ['phone_invalid'])


def downgrade() -> None:
    # Supprimer l'index
    op.drop_index(op.f('ix_patients_phone_invalid'), table_name='patients')
    
    # Supprimer les colonnes
    op.drop_column('patients', 'phone_invalid_at')
    op.drop_column('patients', 'phone_invalid_reason')
    op.drop_column('patients', 'phone_invalid')

