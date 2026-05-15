"""
Tâches Celery Beat (scheduler) pour HelloJADE

Tâches périodiques pour :
- Déclenchement automatique des appels planifiés (process_pending_calls)
- Génération de rapports
- Nettoyage et maintenance
"""
from typing import Dict, Any
from datetime import datetime, timedelta, timezone

from app.tasks import celery_app
from app.core.logging import get_logger
from app.database import AsyncSessionLocal
from app.models.patient import Patient
from app.models.call import Call
from sqlalchemy import select

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Appels planifiés automatiques
# ─────────────────────────────────────────────────────────────────────────────

@celery_app.task(name="app.tasks.scheduler_tasks.process_pending_calls")
def process_pending_calls() -> Dict[str, Any]:
    """
    Déclenche les appels automatiques dont l'heure planifiée est passée,
    en respectant la fenêtre horaire et les jours configurés dans les paramètres d'appel.

    Planifié toutes les 5 minutes par Celery Beat.
    """
    import asyncio
    return asyncio.run(_do_process_pending_calls())


async def _do_process_pending_calls() -> Dict[str, Any]:
    from app.services.call_settings_service import call_settings_service, is_within_call_window
    from app.services.telephony.asterisk_ari_service import asterisk_ari_service

    cs = await call_settings_service.get()
    now = datetime.now(timezone.utc)

    # Vérifier la fenêtre horaire avant de faire quoi que ce soit
    if not is_within_call_window(cs, now):
        from app.services.call_settings_service import _to_brussels
        now_local = _to_brussels(now)
        return {
            "status": "skipped",
            "reason": "outside_call_window",
            "current_time": now_local.strftime("%A %H:%M"),
            "window": f"{cs.get('call_window_start')}–{cs.get('call_window_end')}",
            "allowed_days": cs.get("allowed_days"),
        }

    if not asterisk_ari_service.is_configured:
        logger.warning("[Scheduler] ARI non configuré — aucun appel déclenché")
        return {"status": "skipped", "reason": "ari_not_configured"}

    # Récupérer les patients à appeler
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Patient).where(
                Patient.next_call_scheduled <= now,
                Patient.next_call_scheduled.isnot(None),
                Patient.status == "actif",
                Patient.consent_given.is_(True),
                Patient.telephone.isnot(None),
                Patient.manually_recalled.is_(False),
            )
        )
        patients = list(result.scalars().all())

    if not patients:
        return {"status": "ok", "initiated": 0, "reason": "no_patients_due"}

    logger.info(f"[Scheduler] {len(patients)} patient(s) à appeler")
    initiated = 0
    errors = 0

    for patient in patients:
        try:
            async with AsyncSessionLocal() as db:
                # Recharger le patient dans cette session pour l'update
                p = await db.get(Patient, patient.id)
                if not p:
                    continue
                # Effacer le créneau AVANT l'appel pour éviter les doublons
                p.next_call_scheduled = None

                call = Call(
                    patient_id=p.id,
                    caller_number=asterisk_ari_service.caller_number,
                    callee_number=p.telephone,
                    status="pending",
                    start_time=now,
                    call_metadata={"provider": "asterisk_ari", "scheduled": True},
                )
                db.add(call)
                await db.commit()
                await db.refresh(call)

            channel_id = await asterisk_ari_service.originate(
                phone_number=patient.telephone,
                patient_id=str(patient.id),
                call_db_id=str(call.id),
            )

            async with AsyncSessionLocal() as db:
                call_db = await db.get(Call, call.id)
                p2 = await db.get(Patient, patient.id)
                if call_db:
                    if channel_id:
                        call_db.asterisk_channel = channel_id
                        call_db.call_metadata = {
                            **(call_db.call_metadata or {}),
                            "channel_id": channel_id,
                        }
                        initiated += 1
                        logger.info(
                            f"[Scheduler] Appel initié: patient={patient.id} "
                            f"channel={channel_id}"
                        )
                    else:
                        # L'originate ARI a échoué (Asterisk injoignable, etc.)
                        # Replanifier selon retry_delay_hours si tentatives restantes
                        call_db.status = "failed"
                        call_db.failure_reason = "ARI originate échoué"
                        errors += 1
                        logger.error(
                            f"[Scheduler] Échec originate pour patient={patient.id}"
                        )
                        if p2:
                            from sqlalchemy import func as sa_func
                            from app.services.call_settings_service import next_valid_window
                            failed_count_res = await db.execute(
                                select(sa_func.count(Call.id)).where(
                                    Call.patient_id == patient.id,
                                    Call.status.in_(["failed", "no_answer", "busy"]),
                                )
                            )
                            failed_count = failed_count_res.scalar() or 0
                            max_attempts = int(cs.get("max_attempts", 3))
                            retry_delay_hours = int(cs.get("retry_delay_hours", 4))
                            if failed_count < max_attempts:
                                next_call = now + timedelta(hours=retry_delay_hours)
                                p2.next_call_scheduled = next_valid_window(next_call, cs)
                    await db.commit()

        except Exception as exc:
            logger.error(
                f"[Scheduler] Erreur pour patient={patient.id}: {exc}", exc_info=True
            )
            errors += 1

    return {"status": "completed", "initiated": initiated, "errors": errors}


# ─────────────────────────────────────────────────────────────────────────────

@celery_app.task(name="app.tasks.scheduler_tasks.cleanup_old_data")
def cleanup_old_data(days_to_keep: int = 365) -> Dict[str, Any]:
    """
    Nettoyer les anciennes données (conformité RGPD)

    Args:
        days_to_keep: Nombre de jours de conservation

    Returns:
        Statistiques de nettoyage
    """
    import asyncio

    async def _cleanup():
        async with AsyncSessionLocal() as db:
            cutoff_date = datetime.now() - timedelta(days=days_to_keep)

            stmt = select(Call).where(Call.created_at < cutoff_date)
            result = await db.execute(stmt)
            old_calls = result.scalars().all()

            deleted_count = 0
            for call in old_calls:
                await db.delete(call)
                deleted_count += 1

            await db.commit()

            logger.info(f"Nettoyage: {deleted_count} appels supprimés")
            return {
                "status": "completed",
                "deleted_calls": deleted_count,
            }

    return asyncio.run(_cleanup())


@celery_app.task(name="app.tasks.scheduler_tasks.update_patient_risk_scores")
def update_patient_risk_scores() -> Dict[str, Any]:
    """
    Met à jour les scores de risque des patients basés sur leurs derniers appels
    """
    import asyncio

    async def _update_scores():
        async with AsyncSessionLocal() as db:
            stmt = select(Patient).where(Patient.status == "actif")
            result = await db.execute(stmt)
            patients = result.scalars().all()

            updated = 0

            for patient in patients:
                from app.models.analysis import Analysis

                stmt = select(Analysis).join(Call).where(
                    Call.patient_id == patient.id
                ).order_by(Analysis.created_at.desc()).limit(1)

                result = await db.execute(stmt)
                last_analysis = result.scalar_one_or_none()

                if last_analysis and last_analysis.risk_score != patient.risk_score:
                    patient.risk_score = last_analysis.risk_score
                    updated += 1

            await db.commit()

            logger.info(f"Scores de risque mis à jour: {updated} patients")
            return {
                "status": "completed",
                "updated": updated,
            }

    return asyncio.run(_update_scores())
