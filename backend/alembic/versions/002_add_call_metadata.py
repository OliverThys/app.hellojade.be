"""Add metadata field to calls table

Revision ID: 002_add_call_metadata
Revises: 001_initial
Create Date: 2025-01-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '002_add_call_metadata'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ajouter le champ metadata JSONB à la table calls
    op.add_column(
        'calls',
        sa.Column(
            'metadata',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default='{}'
        )
    )


def downgrade() -> None:
    # Supprimer le champ metadata
    op.drop_column('calls', 'metadata')

