"""Add interrupted status to call_status enum

Revision ID: 004_add_interrupted_status
Revises: 003_add_call_retry_fields
Create Date: 2025-01-20 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '004_add_interrupted_status'
down_revision: Union[str, None] = '003_add_call_retry_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ajouter le statut "interrupted" à l'enum call_status
    # Note: PostgreSQL nécessite de créer un nouvel enum et de migrer les données
    op.execute("""
        ALTER TYPE call_status ADD VALUE IF NOT EXISTS 'interrupted';
    """)


def downgrade() -> None:
    # Note: PostgreSQL ne permet pas de supprimer une valeur d'un enum directement
    # Il faudrait recréer l'enum sans 'interrupted' et migrer les données
    # Pour l'instant, on laisse la valeur (elle ne sera simplement plus utilisée)
    pass

