"""
Tâches Celery pour la génération de rapports PDF

Tâches asynchrones pour :
- Génération de rapports PDF
- Batch generation
- Envoi par email
"""
from typing import List, Dict, Any
from uuid import UUID

from app.tasks import celery_app
from app.core.logging import get_logger
from app.core.config import settings
from app.services.report_service import report_service
from app.services.hl7_epicura_service import epicura_hl7_service
from app.database import AsyncSessionLocal
from app.models.call import Call
from app.models.report import Report
from sqlalchemy import select

logger = get_logger(__name__)


@celery_app.task(name="app.tasks.report_tasks.generate_report_async")
def generate_report_async(call_id: str, report_type: str = "standard") -> Dict[str, Any]:
    """
    Générer un rapport PDF de manière asynchrone

    Args:
        call_id: ID de l'appel (UUID en string)
        report_type: Type de rapport

    Returns:
        Chemin du fichier PDF généré
    """
    import asyncio
    from app.database import async_engine

    async def _generate():
        # Dispose le pool de connexions hérité du process parent (fork Celery)
        # pour éviter le "RuntimeError: Event loop is closed" sur les sockets SQLAlchemy.
        await async_engine.dispose()

        async with AsyncSessionLocal() as db:
            call = await db.get(Call, UUID(call_id))
            if not call:
                logger.error(f"Appel {call_id} non trouvé")
                return {"error": "Call not found"}
            
            # Charger les relations
            await db.refresh(call, ["patient", "transcription", "analysis"])
            
            # Préparer les données
            call_data = {
                "id":         str(call.id),
                "created_at": call.created_at.isoformat() if call.created_at else None,
                "duration":   call.duration,
                "status":     call.status,
                "attempts":   getattr(call, "attempts", None) or 0,
            }
            
            p = call.patient
            patient_data = {
                "nom":                     p.nom,
                "prenom":                  p.prenom,
                "date_naissance":          p.date_naissance.isoformat() if p.date_naissance else None,
                "numero_dossier":          p.numero_dossier,
                "telephone":               p.telephone,
                "service_hospitalisation": p.service_hospitalisation,
                "medecin_referent":        p.medecin_responsable,
                "diagnostic_principal":    p.diagnostic_principal,
            }
            
            transcription_data = None
            if call.transcription:
                raw_segments = call.transcription.segments
                if isinstance(raw_segments, dict):
                    segments_list = raw_segments.get("segments") or []
                elif isinstance(raw_segments, list):
                    segments_list = raw_segments
                else:
                    segments_list = []
                transcription_data = {
                    "full_text": call.transcription.full_text,
                    "language": call.transcription.language,
                    "confidence": call.transcription.confidence,
                    "segments": segments_list or None,
                }

            analysis_data = None
            if call.analysis:
                a = call.analysis
                analysis_data = {
                    "has_pain": a.has_pain,
                    "pain_level": a.pain_level,
                    "pain_relieved": a.pain_relieved,
                    "eating_normally": a.eating_normally,
                    "eating_difficulty_score": a.eating_difficulty_score,
                    "has_nausea": a.has_nausea,
                    "blood_in_vomit": a.blood_in_vomit,
                    "has_headache": a.has_headache,
                    "headache_level": a.headache_level,
                    "has_bleeding": a.has_bleeding,
                    "bleeding_stopped": a.bleeding_stopped,
                    "infection_signs": a.infection_signs,
                    "contacted_emergency": a.contacted_emergency,
                    "emergency_reason": a.emergency_reason,
                    "understands_instructions": a.understands_instructions,
                    "instruction_doubts": a.instruction_doubts,
                    "pain_location": a.pain_location,
                    "pain_description": a.pain_description,
                    "has_fever": a.has_fever,
                    "fever_temperature": a.fever_temperature,
                    "fever_duration": a.fever_duration,
                    "takes_medication": a.takes_medication,
                    "medication_regularity": a.medication_regularity,
                    "medication_issues": a.medication_issues,
                    "moral_state": a.moral_state,
                    "moral_description": a.moral_description,
                    "summary": a.summary,
                    "alerts": a.alerts,
                    "recommendations": a.recommendations,
                    "risk_score": a.risk_score,
                }
            
            raw_meta = getattr(call, "call_metadata", None)
            call_meta = raw_meta if isinstance(raw_meta, dict) else None

            # Générer le PDF
            pdf_path = report_service.generate_call_report(
                call_data=call_data,
                patient_data=patient_data,
                transcription_data=transcription_data,
                analysis_data=analysis_data,
                call_metadata=call_meta,
                report_type=report_type,
            )

            # Enregistrer la ligne Report en DB (sinon l'API /reports/by-call n'a pas de rapport à exposer)
            import os
            existing_stmt = select(Report).where(Report.call_id == UUID(call_id)).limit(1)
            existing_result = await db.execute(existing_stmt)
            if not existing_result.scalar_one_or_none():
                file_size = os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 0
                report = Report(
                    call_id=UUID(call_id),
                    analysis_id=call.analysis.id if call.analysis else None,
                    report_type=report_type,
                    file_path=pdf_path,
                    file_size=file_size,
                    status="generated",
                )
                db.add(report)
                await db.commit()
                logger.info(f"✅ Rapport DB créé: {pdf_path}")
            else:
                logger.info(f"✅ Rapport PDF généré (DB déjà existante): {pdf_path}")

            return {
                "status": "completed",
                "file_path": pdf_path,
                "call_id": call_id,
            }

    # Créer un event loop propre dans le worker forké pour éviter les conflits
    # avec le loop du process parent (SQLAlchemy async engine).
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_generate())
    finally:
        loop.close()
        asyncio.set_event_loop(None)


@celery_app.task(name="app.tasks.report_tasks.generate_pending_reports")
def generate_pending_reports() -> Dict[str, Any]:
    """
    Génère les rapports en attente pour les appels complétés

    Cette tâche est exécutée périodiquement par Celery Beat
    """
    import asyncio
    from app.database import async_engine

    async def _generate_pending():
        await async_engine.dispose()
        async with AsyncSessionLocal() as db:
            # Trouver les appels terminés (complétés ou interrompus) sans rapport
            stmt = select(Call).where(
                Call.status.in_(["completed", "interrupted"])
            ).where(
                ~select(Report.call_id).where(Report.call_id == Call.id).exists()
            ).limit(10)  # Limiter à 10 pour éviter surcharge
            
            result = await db.execute(stmt)
            calls = result.scalars().all()
            
            generated = 0
            errors = 0
            
            for call in calls:
                try:
                    generate_report_async.delay(str(call.id), "standard")
                    generated += 1
                except Exception as e:
                    logger.error(f"Erreur génération rapport pour {call.id}: {e}")
                    errors += 1
            
            logger.info(f"Rapports générés: {generated}, Erreurs: {errors}")
            return {
                "status": "completed",
                "generated": generated,
                "errors": errors,
            }

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_generate_pending())
    finally:
        loop.close()
        asyncio.set_event_loop(None)


@celery_app.task(name="app.tasks.report_tasks.generate_report_batch")
def generate_report_batch(call_ids: List[str], report_type: str = "standard") -> List[Dict[str, Any]]:
    """
    Générer plusieurs rapports en batch
    
    Args:
        call_ids: Liste des IDs d'appels
        report_type: Type de rapport
    
    Returns:
        Liste des résultats
    """
    results = []
    
    for call_id in call_ids:
        try:
            generate_report_async.delay(call_id, report_type)
            results.append({"call_id": call_id, "status": "dispatched"})
        except Exception as e:
            logger.error(f"Erreur batch génération pour {call_id}: {e}")
            results.append({"call_id": call_id, "status": "error", "error": str(e)})
    
    return results


@celery_app.task(name="app.tasks.report_tasks.retry_pending_oru")
def retry_pending_oru() -> Dict[str, Any]:
    """
    Réessaie l'envoi des messages HL7 ORU pour les rapports
    générés mais non envoyés à Mirth.

    Exécuté périodiquement par Celery Beat.
    """
    import asyncio
    from pathlib import Path
    from app.database import async_engine

    async def _retry():
        await async_engine.dispose()
        async with AsyncSessionLocal() as db:
            # Rapports générés mais pas encore envoyés
            stmt = select(Report).where(Report.status == "generated").limit(20)
            result = await db.execute(stmt)
            reports = result.scalars().all()

            sent = 0
            errors = 0

            if not settings.HL7_AUTO_SEND_ORU:
                logger.debug("HL7_AUTO_SEND_ORU désactivé — envoi ORU ignoré")
                return {"sent": 0, "errors": 0, "skipped": len(reports)}

            for report in reports:
                # Chercher le fichier HL7 correspondant
                call_id = str(report.call_id)
                hl7_dir = Path("/app/reports/hl7")
                hl7_files = sorted(hl7_dir.glob(f"oru_{call_id}_*.hl7"), reverse=True)

                if not hl7_files:
                    continue

                hl7_path = str(hl7_files[0])
                try:
                    send_result = await epicura_hl7_service.send_oru(hl7_path)
                    if send_result.get("success"):
                        report.status = "sent"
                        sent += 1
                    else:
                        errors += 1
                except Exception as e:
                    logger.error(f"Retry ORU échoué pour {call_id}: {e}")
                    errors += 1

            await db.commit()
            logger.info(f"Retry ORU: {sent} envoyés, {errors} erreurs")
            return {"sent": sent, "errors": errors}

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_retry())
    finally:
        loop.close()
        asyncio.set_event_loop(None)

