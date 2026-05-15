"""Add new questionnaire fields to Analysis table

Revision ID: 007_add_new_questionnaire_fields
Revises: 006_add_phone_invalid_fields
Create Date: 2025-01-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '007_add_new_questionnaire_fields'
down_revision: Union[str, None] = '006_add_phone_invalid_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ajouter les nouveaux champs du questionnaire de suivi postopératoire

    # 1. Douleur
    op.add_column('analyses', sa.Column('has_pain', sa.Boolean(), nullable=True, comment='Présence de douleur'))
    op.add_column('analyses', sa.Column('pain_relieved', sa.Boolean(), nullable=True, comment='Douleur soulagée par les anti-douleur'))

    # 2. Alimentation
    op.add_column('analyses', sa.Column('eating_normally', sa.Boolean(), nullable=True, comment='Mange normalement'))
    op.add_column('analyses', sa.Column('eating_difficulty_score', sa.Integer(), nullable=True, comment='Score de difficulté à manger (0-10)'))
    op.add_column('analyses', sa.Column('drinking_possible', sa.Boolean(), nullable=True, comment='Peut boire normalement'))

    # 3. Nausées / Vomissements
    op.add_column('analyses', sa.Column('has_nausea', sa.Boolean(), nullable=True, comment='Présence de nausées ou vomissements'))
    op.add_column('analyses', sa.Column('nausea_severity_score', sa.Integer(), nullable=True, comment='Score de sévérité des nausées (0-10)'))
    op.add_column('analyses', sa.Column('blood_in_vomit', sa.Boolean(), nullable=True, comment='Sang dans les vomissements'))

    # 4. Maux de tête
    op.add_column('analyses', sa.Column('has_headache', sa.Boolean(), nullable=True, comment='Présence de maux de tête'))
    op.add_column('analyses', sa.Column('headache_level', sa.Integer(), nullable=True, comment='Niveau des maux de tête (0-10)'))

    # 5. Saignements
    op.add_column('analyses', sa.Column('has_bleeding', sa.Boolean(), nullable=True, comment='Présence de saignements'))
    op.add_column('analyses', sa.Column('bleeding_abundance_score', sa.Integer(), nullable=True, comment="Score d'abondance des saignements (0-10)"))
    op.add_column('analyses', sa.Column('bleeding_stopped', sa.Boolean(), nullable=True, comment='Saignements arrêtés'))
    op.add_column('analyses', sa.Column('infection_signs', sa.Boolean(), nullable=True, comment='Signes d\'infection (suintement, rougeur)'))

    # 6. Contact médical (emergency_reason existe déjà, on ajoute juste contacted_emergency si besoin)
    # Vérifier si la colonne existe déjà
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('analyses')]

    if 'contacted_emergency' not in columns:
        op.add_column('analyses', sa.Column('contacted_emergency', sa.Boolean(), nullable=True, comment='A contacté médecin ou urgences'))
    if 'emergency_reason' not in columns:
        op.add_column('analyses', sa.Column('emergency_reason', sa.Text(), nullable=True, comment='Raison du contact médical'))

    # 7. Consignes postopératoires
    if 'understands_instructions' not in columns:
        op.add_column('analyses', sa.Column('understands_instructions', sa.Boolean(), nullable=True, comment='Comprend les consignes postopératoires'))
    if 'instruction_doubts' not in columns:
        op.add_column('analyses', sa.Column('instruction_doubts', sa.Text(), nullable=True, comment='Doutes sur les consignes'))


def downgrade() -> None:
    # Retirer les nouveaux champs
    op.drop_column('analyses', 'instruction_doubts')
    op.drop_column('analyses', 'understands_instructions')
    op.drop_column('analyses', 'emergency_reason')
    op.drop_column('analyses', 'contacted_emergency')
    op.drop_column('analyses', 'infection_signs')
    op.drop_column('analyses', 'bleeding_stopped')
    op.drop_column('analyses', 'bleeding_abundance_score')
    op.drop_column('analyses', 'has_bleeding')
    op.drop_column('analyses', 'headache_level')
    op.drop_column('analyses', 'has_headache')
    op.drop_column('analyses', 'blood_in_vomit')
    op.drop_column('analyses', 'nausea_severity_score')
    op.drop_column('analyses', 'has_nausea')
    op.drop_column('analyses', 'drinking_possible')
    op.drop_column('analyses', 'eating_difficulty_score')
    op.drop_column('analyses', 'eating_normally')
    op.drop_column('analyses', 'pain_relieved')
    op.drop_column('analyses', 'has_pain')
