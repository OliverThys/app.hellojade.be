"""Add patient_documents table

Revision ID: 010_add_patient_documents
Revises: 009_add_followup_fields
Create Date: 2026-03-31 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '010_add_patient_documents'
down_revision: Union[str, None] = '009_add_followup_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'patient_documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('patient_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('patients.id', ondelete='CASCADE'), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('original_filename', sa.String(255), nullable=False),
        sa.Column('file_path', sa.String(500), nullable=False),
        sa.Column('file_size', sa.Integer, nullable=True),
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_patient_documents_patient_id', 'patient_documents', ['patient_id'])


def downgrade() -> None:
    op.drop_index('ix_patient_documents_patient_id', 'patient_documents')
    op.drop_table('patient_documents')
