"""
Service GDPR pour la conformité RGPD (export/suppression de données)
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.call import Call
from app.models.patient import Patient
from app.models.report import Report
from app.models.transcription import Transcription
from app.models.analysis import Analysis
from app.services.audit_service import audit_service
from app.services.config_service import config_service
from app.core.config import settings as app_settings


class GDPRService:
    """Service de gestion GDPR (RGPD)"""

    @staticmethod
    async def get_effective_data_retention_years(db: AsyncSession) -> int:
        """
        Durée de rétention affichée / utilisée côté conformité : table `settings`
        si présente, sinon variable d'environnement / défaut Pydantic.
        """
        raw = await config_service.get_raw_value("GDPR_DATA_RETENTION_YEARS", db)
        if raw:
            try:
                n = int(str(raw).strip())
                return max(1, min(80, n))
            except ValueError:
                pass
        return int(app_settings.GDPR_DATA_RETENTION_YEARS)

    @staticmethod
    async def export_patient_data(
        db: AsyncSession,
        patient_id: UUID,
        user_id: UUID,
        user_email: str,
    ) -> Dict[str, Any]:
        """
        Exporte toutes les données d'un patient au format JSON (conformité RGPD)
        
        Args:
            db: Session de base de données
            patient_id: ID du patient
            user_id: ID de l'utilisateur qui effectue l'export
            user_email: Email de l'utilisateur
        
        Returns:
            Dictionnaire contenant toutes les données du patient
        """
        # Récupérer le patient
        patient = await db.get(Patient, patient_id)
        if not patient:
            raise ValueError("Patient non trouvé")
        
        retention_years = await GDPRService.get_effective_data_retention_years(db)

        # Construire l'export
        export_data = {
            "export_date": datetime.now().isoformat(),
            "data_retention_policy_years": retention_years,
            "patient": {
                "id": str(patient.id),
                "nom": patient.nom,
                "prenom": patient.prenom,
                "email": patient.email,
                "telephone": patient.telephone,
                "numero_dossier": patient.numero_dossier,
                "date_naissance": patient.date_naissance.isoformat() if patient.date_naissance else None,
                "date_sortie": patient.date_sortie.isoformat() if patient.date_sortie else None,
                "service_hospitalisation": patient.service_hospitalisation,
                "diagnostic_principal": patient.diagnostic_principal,
                "status": patient.status,
                "consent_given": patient.consent_given,
                "consent_date": patient.consent_date.isoformat() if patient.consent_date else None,
                "risk_score": patient.risk_score,
                "notes": patient.notes,
                "created_at": patient.created_at.isoformat() if patient.created_at else None,
                "updated_at": patient.updated_at.isoformat() if patient.updated_at else None,
            },
        }
        
        # Récupérer les appels
        calls_stmt = select(Call).where(Call.patient_id == patient_id)
        calls_result = await db.execute(calls_stmt)
        calls = calls_result.scalars().all()
        
        export_data["calls"] = []
        for call in calls:
            call_data = {
                "id": str(call.id),
                "status": call.status,
                "callee_number": call.callee_number,
                "duration": call.duration,
                "created_at": call.created_at.isoformat() if call.created_at else None,
                "start_time": call.start_time.isoformat() if call.start_time else None,
                "end_time": call.end_time.isoformat() if call.end_time else None,
                "failure_reason": call.failure_reason,
            }
            
            # Transcription
            if call.transcription:
                await db.refresh(call, ["transcription"])
                call_data["transcription"] = {
                    "full_text": call.transcription.full_text,
                    "language": call.transcription.language,
                    "confidence": call.transcription.confidence,
                    "created_at": call.transcription.created_at.isoformat() if call.transcription.created_at else None,
                }
            
            # Analyse
            if call.analysis:
                await db.refresh(call, ["analysis"])
                call_data["analysis"] = {
                    "pain_level": call.analysis.pain_level,
                    "pain_location": call.analysis.pain_location,
                    "pain_description": call.analysis.pain_description,
                    "has_fever": call.analysis.has_fever,
                    "fever_temperature": call.analysis.fever_temperature,
                    "takes_medication": call.analysis.takes_medication,
                    "moral_state": call.analysis.moral_state,
                    "summary": call.analysis.summary,
                    "risk_score": call.analysis.risk_score,
                    "created_at": call.analysis.created_at.isoformat() if call.analysis.created_at else None,
                }
            
            export_data["calls"].append(call_data)
        
        # Récupérer les rapports
        reports_stmt = select(Report).join(Call).where(Call.patient_id == patient_id)
        reports_result = await db.execute(reports_stmt)
        reports = reports_result.scalars().all()
        
        export_data["reports"] = [
            {
                "id": str(report.id),
                "report_type": report.report_type,
                "status": report.status,
                "created_at": report.created_at.isoformat() if report.created_at else None,
                "file_size": report.file_size,
            }
            for report in reports
        ]
        
        # Récupérer les logs d'audit liés au patient
        audit_logs, _ = await audit_service.get_audit_logs(
            db=db,
            resource_type="patient",
            resource_id=patient_id,
            limit=1000,
        )
        
        export_data["audit_trail"] = [
            {
                "action": log.action,
                "user_email": log.user_email,
                "created_at": log.created_at.isoformat(),
                "details": log.details,
            }
            for log in audit_logs
        ]
        
        # Logger l'export
        await audit_service.log_action(
            db=db,
            action="export_patient_data",
            user_id=user_id,
            user_email=user_email,
            resource_type="patient",
            resource_id=patient_id,
            resource_name=f"{patient.prenom} {patient.nom}",
            details={
                "export_date": datetime.now().isoformat(),
                "data_included": {
                    "patient": True,
                    "calls": len(export_data["calls"]),
                    "reports": len(export_data["reports"]),
                    "audit_logs": len(export_data["audit_trail"]),
                },
            },
        )
        
        return export_data

    @staticmethod
    async def delete_patient_data(
        db: AsyncSession,
        patient_id: UUID,
        user_id: UUID,
        user_email: str,
    ) -> Dict[str, Any]:
        """
        Supprime/anonymise les données d'un patient (conformité RGPD)
        
        Note: Ne supprime pas physiquement les données pour des raisons légales,
        mais les anonymise complètement.
        
        Args:
            db: Session de base de données
            patient_id: ID du patient
            user_id: ID de l'utilisateur qui effectue la suppression
            user_email: Email de l'utilisateur
        
        Returns:
            Dictionnaire avec le résultat de l'opération
        """
        # Récupérer le patient
        patient = await db.get(Patient, patient_id)
        if not patient:
            raise ValueError("Patient non trouvé")
        
        # Sauvegarder le nom pour le log
        original_name = f"{patient.prenom} {patient.nom}"
        
        # Anonymiser les données du patient
        patient.nom = "ANONYMIZED"
        patient.prenom = "ANONYMIZED"
        patient.email = None
        patient.telephone = None
        patient.date_naissance = None
        patient.numero_dossier = f"ANONYMIZED-{patient_id.hex[:8]}"
        patient.service_hospitalisation = None
        patient.diagnostic_principal = None
        patient.notes = None
        patient.status = "archived"
        patient.consent_given = False
        patient.consent_date = None
        
        # Anonymiser les transcriptions (supprimer le texte)
        calls_stmt = select(Call).where(Call.patient_id == patient_id)
        calls_result = await db.execute(calls_stmt)
        calls = calls_result.scalars().all()
        
        for call in calls:
            # Supprimer l'enregistrement audio (chemin)
            call.recording_path = None
            call.recording_url = None
            
            # Anonymiser la transcription si elle existe
            if call.transcription:
                await db.refresh(call, ["transcription"])
                call.transcription.full_text = "[Données anonymisées conformément au RGPD]"
            
            # Anonymiser l'analyse si elle existe
            if call.analysis:
                await db.refresh(call, ["analysis"])
                call.analysis.summary = "[Données anonymisées conformément au RGPD]"
                call.analysis.pain_description = None
                call.analysis.moral_description = None
                call.analysis.alerts = None
                call.analysis.recommendations = None
        
        # Marquer les rapports comme archivés
        reports_stmt = select(Report).join(Call).where(Call.patient_id == patient_id)
        reports_result = await db.execute(reports_stmt)
        reports = reports_result.scalars().all()
        
        for report in reports:
            report.status = "archived"
            # Note: Ne pas supprimer le fichier PDF, mais le marquer comme archivé
        
        await db.commit()
        
        # Logger la suppression
        await audit_service.log_action(
            db=db,
            action="delete_patient_data",
            user_id=user_id,
            user_email=user_email,
            resource_type="patient",
            resource_id=patient_id,
            resource_name=original_name,
            details={
                "deletion_date": datetime.now().isoformat(),
                "anonymization_applied": True,
                "calls_affected": len(calls),
                "reports_archived": len(reports),
            },
        )
        
        return {
            "status": "success",
            "message": "Données patient anonymisées avec succès",
            "patient_id": str(patient_id),
            "calls_affected": len(calls),
            "reports_archived": len(reports),
        }

    @staticmethod
    async def get_patient_audit_trail(
        db: AsyncSession,
        patient_id: UUID,
    ) -> List[Dict[str, Any]]:
        """
        Récupère la traçabilité complète des accès aux données d'un patient
        
        Args:
            db: Session de base de données
            patient_id: ID du patient
        
        Returns:
            Liste des logs d'audit liés au patient
        """
        logs, _ = await audit_service.get_audit_logs(
            db=db,
            resource_type="patient",
            resource_id=patient_id,
            limit=1000,
        )
        
        return [
            {
                "id": str(log.id),
                "action": log.action,
                "user_id": str(log.user_id) if log.user_id else None,
                "user_email": log.user_email,
                "ip_address": str(log.ip_address) if log.ip_address else None,
                "created_at": log.created_at.isoformat(),
                "details": log.details,
            }
            for log in logs
        ]


gdpr_service = GDPRService()

