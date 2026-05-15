"""Initial migration - create all tables

Revision ID: 001_initial
Revises: 
Create Date: 2025-01-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum types
    op.execute("CREATE TYPE user_role AS ENUM ('admin', 'medecin', 'infirmier', 'operateur')")
    op.execute("CREATE TYPE patient_status AS ENUM ('actif', 'inactif', 'prioritaire', 'urgence')")
    op.execute("""
        CREATE TYPE call_status AS ENUM (
            'pending', 'ringing', 'in_progress', 'completed', 
            'failed', 'no_answer', 'busy', 'cancelled'
        )
    """)
    
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('username', sa.String(100), nullable=False, unique=True),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('full_name', sa.String(200), nullable=True),
        sa.Column('role', sa.Enum('admin', 'medecin', 'infirmier', 'operateur', name='user_role'), nullable=False, server_default='operateur'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('last_login', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    
    # Create patients table
    op.create_table(
        'patients',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('oracle_patient_id', sa.Integer(), nullable=False, unique=True, comment='ID du patient dans la base Oracle'),
        sa.Column('numero_dossier', sa.String(50), nullable=False, unique=True),
        sa.Column('nom', sa.String(100), nullable=False),
        sa.Column('prenom', sa.String(100), nullable=False),
        sa.Column('telephone', sa.String(20), nullable=True),
        sa.Column('email', sa.String(100), nullable=True),
        sa.Column('date_naissance', sa.DateTime(), nullable=True),
        sa.Column('sexe', sa.String(1), nullable=True),
        sa.Column('adresse', sa.String(200), nullable=True),
        sa.Column('ville', sa.String(100), nullable=True),
        sa.Column('code_postal', sa.String(10), nullable=True),
        sa.Column('service_hospitalisation', sa.String(100), nullable=True),
        sa.Column('date_admission', sa.DateTime(), nullable=True),
        sa.Column('date_sortie', sa.DateTime(), nullable=True),
        sa.Column('diagnostic_principal', sa.String(500), nullable=True),
        sa.Column('medecin_responsable', sa.String(150), nullable=True),
        sa.Column('status', sa.Enum('actif', 'inactif', 'prioritaire', 'urgence', name='patient_status'), nullable=False, server_default='actif'),
        sa.Column('last_call_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_call_scheduled', sa.DateTime(timezone=True), nullable=True),
        sa.Column('risk_score', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('consent_given', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('consent_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('last_sync_oracle', sa.DateTime(timezone=True), nullable=True, comment='Dernière synchronisation avec Oracle'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index(op.f('ix_patients_oracle_patient_id'), 'patients', ['oracle_patient_id'], unique=True)
    op.create_index(op.f('ix_patients_numero_dossier'), 'patients', ['numero_dossier'], unique=True)
    op.create_index(op.f('ix_patients_nom'), 'patients', ['nom'])
    op.create_index(op.f('ix_patients_prenom'), 'patients', ['prenom'])
    op.create_index(op.f('ix_patients_telephone'), 'patients', ['telephone'])
    op.create_index(op.f('ix_patients_status'), 'patients', ['status'])
    op.create_index(op.f('ix_patients_risk_score'), 'patients', ['risk_score'])
    
    # Create calls table
    op.create_table(
        'calls',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('patient_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('initiated_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('asterisk_call_id', sa.String(100), nullable=True, unique=True),
        sa.Column('asterisk_channel', sa.String(200), nullable=True),
        sa.Column('caller_number', sa.String(20), nullable=False),
        sa.Column('callee_number', sa.String(20), nullable=False),
        sa.Column('status', sa.Enum('pending', 'ringing', 'in_progress', 'completed', 'failed', 'no_answer', 'busy', 'cancelled', name='call_status'), nullable=False, server_default='pending'),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('answer_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration', sa.Integer(), nullable=True, comment='Durée en secondes'),
        sa.Column('recording_path', sa.String(500), nullable=True),
        sa.Column('recording_size', sa.Integer(), nullable=True, comment='Taille en octets'),
        sa.Column('failure_reason', sa.String(200), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['initiated_by'], ['users.id'], ondelete='SET NULL'),
    )
    op.create_index(op.f('ix_calls_patient_id'), 'calls', ['patient_id'])
    op.create_index(op.f('ix_calls_initiated_by'), 'calls', ['initiated_by'])
    op.create_index(op.f('ix_calls_asterisk_call_id'), 'calls', ['asterisk_call_id'], unique=True)
    op.create_index(op.f('ix_calls_status'), 'calls', ['status'])
    op.create_index(op.f('ix_calls_start_time'), 'calls', ['start_time'])
    
    # Create transcriptions table
    op.create_table(
        'transcriptions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('call_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('full_text', sa.Text(), nullable=False),
        sa.Column('language', sa.String(10), nullable=False, server_default='fr-BE'),
        sa.Column('whisper_model', sa.String(50), nullable=False, server_default='large-v3'),
        sa.Column('confidence', sa.Float(), nullable=True, comment='Score de confiance global (0.0 à 1.0)'),
        sa.Column('segments', postgresql.JSON(astext_type=sa.Text()), nullable=True, comment='Segments de texte avec timestamps et metadata'),
        sa.Column('processing_time', sa.Float(), nullable=True, comment='Temps de traitement en secondes'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['call_id'], ['calls.id'], ondelete='CASCADE'),
    )
    op.create_index(op.f('ix_transcriptions_call_id'), 'transcriptions', ['call_id'], unique=True)
    
    # Create analyses table
    op.create_table(
        'analyses',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('call_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('transcription_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('pain_level', sa.Integer(), nullable=True, comment='Niveau de douleur de 0 à 10'),
        sa.Column('pain_location', sa.String(200), nullable=True, comment='Localisation de la douleur'),
        sa.Column('pain_description', sa.Text(), nullable=True, comment='Description détaillée de la douleur'),
        sa.Column('has_fever', sa.Boolean(), nullable=True),
        sa.Column('fever_temperature', sa.Float(), nullable=True, comment='Température en degrés Celsius'),
        sa.Column('fever_duration', sa.String(100), nullable=True, comment='Durée de la fièvre'),
        sa.Column('takes_medication', sa.Boolean(), nullable=True),
        sa.Column('medication_regularity', sa.String(50), nullable=True, comment='Régularité de prise des médicaments'),
        sa.Column('medication_issues', sa.Text(), nullable=True, comment='Problèmes avec les médicaments'),
        sa.Column('moral_state', sa.Integer(), nullable=True, comment='État moral de 1 (très bas) à 5 (très bien)'),
        sa.Column('moral_description', sa.Text(), nullable=True, comment="Description de l'état moral"),
        sa.Column('summary', sa.Text(), nullable=True, comment="Résumé de l'analyse"),
        sa.Column('alerts', postgresql.JSON(astext_type=sa.Text()), nullable=True, comment='Alertes détectées [{type, severity, message, action}]'),
        sa.Column('recommendations', postgresql.JSON(astext_type=sa.Text()), nullable=True, comment='Recommandations médicales'),
        sa.Column('risk_score', sa.Integer(), nullable=False, server_default='0', comment='Score de risque global de 0 à 10'),
        sa.Column('model_used', sa.String(50), nullable=False, server_default='llama3.1:8b'),
        sa.Column('processing_time', sa.Float(), nullable=True, comment='Temps de traitement en secondes'),
        sa.Column('confidence', sa.Float(), nullable=True, comment='Confiance de l\'analyse (0.0 à 1.0)'),
        sa.Column('raw_response', postgresql.JSON(astext_type=sa.Text()), nullable=True, comment='Réponse brute de l\'IA'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['call_id'], ['calls.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['transcription_id'], ['transcriptions.id'], ondelete='SET NULL'),
    )
    op.create_index(op.f('ix_analyses_call_id'), 'analyses', ['call_id'], unique=True)
    op.create_index(op.f('ix_analyses_risk_score'), 'analyses', ['risk_score'])
    
    # Create reports table
    op.create_table(
        'reports',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('call_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('analysis_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('generated_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('report_type', sa.String(50), nullable=False, server_default='standard', comment='Type de rapport (standard, detailed, summary)'),
        sa.Column('file_path', sa.String(500), nullable=False, comment='Chemin vers le fichier PDF'),
        sa.Column('file_size', sa.Integer(), nullable=True, comment='Taille du fichier en octets'),
        sa.Column('file_hash', sa.String(64), nullable=True, comment='Hash SHA256 du fichier'),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending', comment='Status (pending, generated, sent, error)'),
        sa.Column('sent_to', sa.String(200), nullable=True, comment='Adresses email de destination'),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['call_id'], ['calls.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['generated_by'], ['users.id'], ondelete='SET NULL'),
    )
    op.create_index(op.f('ix_reports_call_id'), 'reports', ['call_id'])
    
    # Create audit_logs table
    op.create_table(
        'audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('user_email', sa.String(255), nullable=True, comment='Email de l\'utilisateur au moment de l\'action'),
        sa.Column('action', sa.String(100), nullable=False, comment='Type d\'action (login, logout, view, create, update, delete, export, etc.)'),
        sa.Column('resource_type', sa.String(50), nullable=True, comment='Type de ressource (patient, call, user, report, etc.)'),
        sa.Column('resource_id', postgresql.UUID(as_uuid=True), nullable=True, comment='ID de la ressource affectée'),
        sa.Column('resource_name', sa.String(200), nullable=True, comment='Nom ou description de la ressource'),
        sa.Column('details', postgresql.JSON(astext_type=sa.Text()), nullable=True, comment='Détails supplémentaires de l\'action'),
        sa.Column('changes', postgresql.JSON(astext_type=sa.Text()), nullable=True, comment='Changements effectués (before/after)'),
        sa.Column('ip_address', postgresql.INET(), nullable=True, comment='Adresse IP de l\'utilisateur'),
        sa.Column('user_agent', sa.Text(), nullable=True, comment='User agent du navigateur'),
        sa.Column('session_id', sa.String(100), nullable=True, comment='ID de session'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    )
    op.create_index(op.f('ix_audit_logs_user_id'), 'audit_logs', ['user_id'])
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'])
    op.create_index(op.f('ix_audit_logs_resource_type'), 'audit_logs', ['resource_type'])
    op.create_index(op.f('ix_audit_logs_resource_id'), 'audit_logs', ['resource_id'])
    op.create_index(op.f('ix_audit_logs_created_at'), 'audit_logs', ['created_at'])
    
    # Create settings table
    op.create_table(
        'settings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('key', sa.String(100), nullable=False, unique=True, comment='Clé unique du paramètre'),
        sa.Column('value', postgresql.JSON(astext_type=sa.Text()), nullable=False, comment='Valeur du paramètre (JSON)'),
        sa.Column('category', sa.String(50), nullable=True, comment='Catégorie (system, asterisk, ai, notification, scheduler, etc.)'),
        sa.Column('description', sa.Text(), nullable=True, comment='Description du paramètre'),
        sa.Column('value_type', sa.String(20), nullable=True, comment='Type de valeur (string, number, boolean, object, array)'),
        sa.Column('validation_schema', postgresql.JSON(astext_type=sa.Text()), nullable=True, comment='Schéma de validation JSON'),
        sa.Column('is_sensitive', sa.Boolean(), nullable=False, server_default='false', comment='Indique si le paramètre contient des données sensibles'),
        sa.Column('encrypted', sa.Boolean(), nullable=False, server_default='false', comment='Indique si la valeur est chiffrée'),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('previous_value', postgresql.JSON(astext_type=sa.Text()), nullable=True, comment='Valeur précédente avant modification'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='SET NULL'),
    )
    op.create_index(op.f('ix_settings_key'), 'settings', ['key'], unique=True)
    op.create_index(op.f('ix_settings_category'), 'settings', ['category'])


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_table('settings')
    op.drop_table('audit_logs')
    op.drop_table('reports')
    op.drop_table('analyses')
    op.drop_table('transcriptions')
    op.drop_table('calls')
    op.drop_table('patients')
    op.drop_table('users')
    
    # Drop enum types
    op.execute('DROP TYPE IF EXISTS call_status')
    op.execute('DROP TYPE IF EXISTS patient_status')
    op.execute('DROP TYPE IF EXISTS user_role')

