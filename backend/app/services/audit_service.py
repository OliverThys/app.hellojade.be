"""
Service de gestion des logs d'audit pour la conformité RGPD
"""
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.schemas.audit_log import AuditLogCreate


class AuditService:
    """Service de gestion des logs d'audit"""

    @staticmethod
    async def log_action(
        db: AsyncSession,
        action: str,
        user_id: Optional[UUID] = None,
        user_email: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[UUID] = None,
        resource_name: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        changes: Optional[Dict[str, Any]] = None,
        request: Optional[Request] = None,
    ) -> AuditLog:
        """
        Enregistre une action dans les logs d'audit
        
        Args:
            db: Session de base de données
            action: Type d'action (login, logout, view, create, update, delete, export, etc.)
            user_id: ID de l'utilisateur
            user_email: Email de l'utilisateur
            resource_type: Type de ressource (patient, call, user, report, etc.)
            resource_id: ID de la ressource
            resource_name: Nom de la ressource
            details: Détails supplémentaires
            changes: Changements effectués (before/after)
            request: Objet Request FastAPI (pour IP, user_agent)
        
        Returns:
            AuditLog créé
        """
        # Extraire les informations de la requête
        ip_address = None
        user_agent = None
        session_id = None
        
        if request:
            # IP address (gérer les proxies)
            if request.client:
                ip_address = request.client.host
            # X-Forwarded-For header pour les reverse proxies
            forwarded_for = request.headers.get("X-Forwarded-For")
            if forwarded_for:
                ip_address = forwarded_for.split(",")[0].strip()
            
            user_agent = request.headers.get("User-Agent")
            session_id = request.headers.get("X-Session-Id")
        
        # Créer le log d'audit
        audit_log = AuditLog(
            user_id=user_id,
            user_email=user_email,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            details=details or {},
            changes=changes or {},
            ip_address=ip_address,
            user_agent=user_agent,
            session_id=session_id,
        )
        
        db.add(audit_log)
        await db.commit()
        await db.refresh(audit_log)
        
        return audit_log

    @staticmethod
    async def get_audit_logs(
        db: AsyncSession,
        user_id: Optional[UUID] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[UUID] = None,
        action: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[AuditLog], int]:
        """
        Récupère les logs d'audit avec filtres
        
        Args:
            db: Session de base de données
            user_id: Filtrer par utilisateur
            resource_type: Filtrer par type de ressource
            resource_id: Filtrer par ID de ressource
            action: Filtrer par action
            start_date: Date de début
            end_date: Date de fin
            limit: Nombre maximum de résultats
            offset: Offset pour la pagination
        
        Returns:
            Tuple (liste de logs, total)
        """
        stmt = select(AuditLog)
        count_stmt = select(AuditLog).with_only_columns(AuditLog.id)
        
        # Appliquer les filtres
        if user_id:
            stmt = stmt.where(AuditLog.user_id == user_id)
            count_stmt = count_stmt.where(AuditLog.user_id == user_id)
        
        if resource_type:
            stmt = stmt.where(AuditLog.resource_type == resource_type)
            count_stmt = count_stmt.where(AuditLog.resource_type == resource_type)
        
        if resource_id:
            stmt = stmt.where(AuditLog.resource_id == resource_id)
            count_stmt = count_stmt.where(AuditLog.resource_id == resource_id)
        
        if action:
            stmt = stmt.where(AuditLog.action == action)
            count_stmt = count_stmt.where(AuditLog.action == action)
        
        if start_date:
            stmt = stmt.where(AuditLog.created_at >= start_date)
            count_stmt = count_stmt.where(AuditLog.created_at >= start_date)
        
        if end_date:
            stmt = stmt.where(AuditLog.created_at <= end_date)
            count_stmt = count_stmt.where(AuditLog.created_at <= end_date)
        
        # Compter le total
        from sqlalchemy import func
        count_result = await db.execute(select(func.count()).select_from(count_stmt.subquery()))
        total = count_result.scalar_one()
        
        # Trier et paginer
        stmt = stmt.order_by(AuditLog.created_at.desc())
        stmt = stmt.limit(limit).offset(offset)
        
        result = await db.execute(stmt)
        logs = result.scalars().all()
        
        return list(logs), total

    @staticmethod
    async def export_audit_logs(
        db: AsyncSession,
        user_id: Optional[UUID] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[UUID] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> list[Dict[str, Any]]:
        """
        Exporte les logs d'audit au format JSON
        
        Args:
            db: Session de base de données
            user_id: Filtrer par utilisateur
            resource_type: Filtrer par type de ressource
            resource_id: Filtrer par ID de ressource
            start_date: Date de début
            end_date: Date de fin
        
        Returns:
            Liste de dictionnaires représentant les logs
        """
        logs, _ = await AuditService.get_audit_logs(
            db=db,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            start_date=start_date,
            end_date=end_date,
            limit=10000,  # Limite élevée pour l'export
        )
        
        # Convertir en dictionnaires
        export_data = []
        for log in logs:
            export_data.append({
                "id": str(log.id),
                "user_id": str(log.user_id) if log.user_id else None,
                "user_email": log.user_email,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": str(log.resource_id) if log.resource_id else None,
                "resource_name": log.resource_name,
                "details": log.details,
                "changes": log.changes,
                "ip_address": str(log.ip_address) if log.ip_address else None,
                "user_agent": log.user_agent,
                "session_id": log.session_id,
                "created_at": log.created_at.isoformat(),
                "is_sensitive_action": log.is_sensitive_action,
                "is_admin_action": log.is_admin_action,
                "is_gdpr_action": log.is_gdpr_action,
            })
        
        return export_data


audit_service = AuditService()

