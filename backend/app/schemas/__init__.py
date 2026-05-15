"""
Schémas Pydantic pour la validation des données
"""

from app.schemas.analysis import (
    AnalysisBase,
    AnalysisCreate,
    AnalysisInDB,
    AnalysisResponse,
    AnalysisUpdate,
)
from app.schemas.audit_log import AuditLogCreate, AuditLogInDB, AuditLogResponse
from app.schemas.call import (
    CallBase,
    CallCreate,
    CallInDB,
    CallResponse,
    CallUpdate,
    CallWithAnalysis,
)
from app.schemas.patient import (
    PatientBase,
    PatientCreate,
    PatientInDB,
    PatientResponse,
    PatientUpdate,
)
from app.schemas.report import ReportCreate, ReportInDB, ReportResponse
from app.schemas.token import Token, TokenPayload
from app.schemas.transcription import (
    TranscriptionCreate,
    TranscriptionInDB,
    TranscriptionResponse,
)
from app.schemas.user import UserCreate, UserInDB, UserLogin, UserResponse, UserUpdate

__all__ = [
    # User
    "UserCreate",
    "UserUpdate",
    "UserLogin",
    "UserResponse",
    "UserInDB",
    # Token
    "Token",
    "TokenPayload",
    # Patient
    "PatientBase",
    "PatientCreate",
    "PatientUpdate",
    "PatientResponse",
    "PatientInDB",
    # Call
    "CallBase",
    "CallCreate",
    "CallUpdate",
    "CallResponse",
    "CallInDB",
    "CallWithAnalysis",
    # Transcription
    "TranscriptionCreate",
    "TranscriptionResponse",
    "TranscriptionInDB",
    # Analysis
    "AnalysisBase",
    "AnalysisCreate",
    "AnalysisUpdate",
    "AnalysisResponse",
    "AnalysisInDB",
    # Report
    "ReportCreate",
    "ReportResponse",
    "ReportInDB",
    # AuditLog
    "AuditLogCreate",
    "AuditLogResponse",
    "AuditLogInDB",
]

