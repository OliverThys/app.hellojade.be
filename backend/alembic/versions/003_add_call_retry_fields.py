"""Add retry fields to calls table

Revision ID: 003_add_call_retry_fields
Revises: 002_add_call_metadata
Create Date: 2025-01-20 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '003_add_call_retry_fields'
down_revision: Union[str, None] = '002_add_call_metadata'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ajouter les champs pour le retry automatique
    op.add_column(
        'calls',
        sa.Column(
            'retry_count',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Nombre de tentatives de retry effectuées'
        )
    )
    
    op.add_column(
        'calls',
        sa.Column(
            'max_retries',
            sa.Integer(),
            nullable=False,
            server_default='3',
            comment='Nombre maximum de tentatives de retry'
        )
    )
    
    op.add_column(
        'calls',
        sa.Column(
            'next_retry_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment='Date/heure de la prochaine tentative de retry'
        )
    )
    
    op.add_column(
        'calls',
        sa.Column(
            'first_call_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment='Date/heure du premier appel (pour calculer les délais de retry)'
        )
    )
    
    # Créer un index sur next_retry_at pour les requêtes de retry
    op.create_index(
        'ix_calls_next_retry_at',
        'calls',
        ['next_retry_at'],
        unique=False
    )
    
    # Créer un index sur first_call_at
    op.create_index(
        'ix_calls_first_call_at',
        'calls',
        ['first_call_at'],
        unique=False
    )


def downgrade() -> None:
    # Supprimer les index
    op.drop_index('ix_calls_first_call_at', table_name='calls')
    op.drop_index('ix_calls_next_retry_at', table_name='calls')
    
    # Supprimer les colonnes
    op.drop_column('calls', 'first_call_at')
    op.drop_column('calls', 'next_retry_at')
    op.drop_column('calls', 'max_retries')
    op.drop_column('calls', 'retry_count')

