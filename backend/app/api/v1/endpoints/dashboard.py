"""
Endpoints pour le tableau de bord
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import get_db
from app.dependencies import get_current_user
from app.models.call import Call
from app.models.patient import Patient
from app.models.report import Report
from app.models.user import User
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/stats", response_model=Dict[str, Any])
async def get_dashboard_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Récupérer les statistiques du tableau de bord (optimisé)"""
    
    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    
    # Optimisation: Combiner toutes les requêtes patients en une seule
    patients_stats_stmt = select(
        func.count(Patient.id).label("total_patients"),
        func.count(Patient.id).filter(Patient.status == "actif").label("active_patients"),
    )
    patients_result = await db.execute(patients_stats_stmt)
    patients_row = patients_result.one()
    total_patients = patients_row.total_patients
    active_patients = patients_row.active_patients
    
    # Optimisation: Combiner toutes les requêtes appels en une seule
    calls_stats_stmt = select(
        func.count(Call.id).label("total_calls"),
        func.count(Call.id).filter(Call.created_at >= today).label("calls_today"),
        func.count(Call.id).filter(Call.created_at >= week_ago).label("calls_this_week"),
        func.count(Call.id).filter(Call.created_at >= month_ago).label("calls_this_month"),
        func.count(Call.id).filter(Call.status == "completed").label("completed_calls"),
        func.count(Call.id).filter(Call.status.in_(["pending", "ringing", "in_progress"])).label("pending_calls"),
        func.count(Call.id).filter(Call.status.in_(["failed", "no_answer", "busy", "cancelled"])).label("failed_calls"),
        func.count(Call.id).filter(
            (Call.created_at >= today) & (Call.status == "completed")
        ).label("successful_calls_today"),
        func.count(Call.id).filter(
            (Call.status.in_(["failed", "no_answer"])) & (Call.created_at >= week_ago)
        ).label("recent_failures"),
        func.count(Call.id).filter(
            (Call.status == "completed") & (Call.created_at >= week_ago)
        ).label("completed_calls_week"),
    )
    calls_result = await db.execute(calls_stats_stmt)
    calls_row = calls_result.one()
    total_calls = calls_row.total_calls
    calls_today = calls_row.calls_today
    calls_this_week = calls_row.calls_this_week
    calls_this_month = calls_row.calls_this_month
    completed_calls = calls_row.completed_calls
    pending_calls = calls_row.pending_calls
    failed_calls = calls_row.failed_calls
    successful_calls_today = calls_row.successful_calls_today
    recent_failures = calls_row.recent_failures
    completed_calls_week = calls_row.completed_calls_week
    
    # Répartition par statut (déjà optimisé)
    calls_by_status_stmt = select(
        Call.status,
        func.count(Call.id).label("count")
    ).group_by(Call.status)
    calls_by_status_result = await db.execute(calls_by_status_stmt)
    calls_by_status = {row.status: row.count for row in calls_by_status_result}
    
    # Optimisation: Appels des 7 derniers jours en une seule requête avec GROUP BY
    date_range_start = (today - timedelta(days=6)).date()
    calls_by_day_stmt = select(
        func.date(Call.created_at).label("date"),
        func.count(Call.id).label("count")
    ).where(
        func.date(Call.created_at) >= date_range_start
    ).group_by(func.date(Call.created_at))
    
    calls_by_day_result = await db.execute(calls_by_day_stmt)
    calls_by_day_dict = {row.date: row.count for row in calls_by_day_result}
    
    # Construire la liste complète avec toutes les dates (même si 0)
    calls_by_day = []
    for i in range(7):
        date = (today - timedelta(days=6-i)).date()
        calls_by_day.append({
            "date": date.isoformat(),
            "count": calls_by_day_dict.get(date, 0)
        })
    
    # Total rapports
    reports_stmt = select(func.count(Report.id))
    reports_result = await db.execute(reports_stmt)
    total_reports = reports_result.scalar_one()

    # Appels avec alerte déclenchée (tout type, transfer désactivé inclus)
    # sur les 7 derniers jours
    alerts_stmt = select(func.count(Call.id)).where(
        Call.call_metadata["alert_triggered"].astext == "true",
        Call.created_at >= week_ago,
    )
    alerts_result = await db.execute(alerts_stmt)
    alerts_count = alerts_result.scalar_one() or 0

    # Alertes par jour (courbe graphique) — toutes alertes déclenchées
    transfers_by_day_stmt = select(
        func.date(Call.created_at).label("date"),
        func.count(Call.id).label("count")
    ).where(
        func.date(Call.created_at) >= date_range_start,
        Call.call_metadata["alert_triggered"].astext == "true",
    ).group_by(func.date(Call.created_at))
    transfers_by_day_result = await db.execute(transfers_by_day_stmt)
    transfers_by_day_dict = {row.date: row.count for row in transfers_by_day_result}

    transfers_by_day = []
    for i in range(7):
        date = (today - timedelta(days=6 - i)).date()
        transfers_by_day.append({
            "date": date.isoformat(),
            "count": transfers_by_day_dict.get(date, 0)
        })

    # Temps économisé : durée cumulée des appels complétés NON transférés (gérés entièrement par JADE)
    # = appels où aucune intervention humaine n'a été nécessaire
    time_saved_stmt = select(func.sum(Call.duration)).where(
        Call.status == "completed",
        Call.duration.isnot(None),
        Call.created_at >= week_ago,
        or_(
            Call.call_metadata["alert_type"].astext != "transfer",
            Call.call_metadata["alert_triggered"].astext != "true",
        ),
    )
    time_saved_result = await db.execute(time_saved_stmt)
    time_saved_seconds = int(time_saved_result.scalar_one() or 0)

    # Patients transférés cette semaine
    transfers_count_stmt = select(func.count(Call.id)).where(
        Call.call_metadata["alert_type"].astext == "transfer",
        Call.created_at >= week_ago,
    )
    transfers_count_result = await db.execute(transfers_count_stmt)
    transfers_count = transfers_count_result.scalar_one() or 0

    # Patients à rappeler par un humain :
    # – alerte déclenchée mais appel non complété
    # – appel interrompu avec alerte
    callbacks_stmt = (
        select(Call)
        .options(joinedload(Call.patient))
        .where(
            Call.call_metadata["alert_triggered"].astext == "true",
            Call.status.in_(["failed", "no_answer", "busy", "cancelled", "interrupted"]),
            Call.created_at >= week_ago,
        )
        .order_by(Call.created_at.desc())
        .limit(20)
    )
    callbacks_result = await db.execute(callbacks_stmt)
    callback_calls = callbacks_result.scalars().unique().all()

    def _callback_reason(call: Call) -> str:
        alert_type = (call.call_metadata or {}).get("alert_type", "")
        if call.status == "interrupted":
            return "Appel interrompu"
        if alert_type == "transfer":
            return "Transfert sans réponse"
        if alert_type == "clinical":
            return "Alerte clinique"
        return "Suivi requis"

    def _patient_name(call: Call) -> str:
        p = call.patient
        if p:
            nom = getattr(p, "nom", None) or getattr(p, "last_name", None) or ""
            prenom = getattr(p, "prenom", None) or getattr(p, "first_name", None) or ""
            name = f"{nom.upper()} {prenom}".strip()
            if name:
                return name
        return (call.call_metadata or {}).get("patient_name") or call.callee_number or "Inconnu"

    callbacks_needed = [
        {
            "call_id": str(call.id),
            "patient_name": _patient_name(call),
            "phone": call.callee_number,
            "reason": _callback_reason(call),
            "status": call.status,
            "created_at": call.created_at.isoformat() if call.created_at else None,
            "duration": call.duration,
        }
        for call in callback_calls
    ]

    return {
        "total_patients": total_patients,
        "active_patients": active_patients,
        "total_calls": total_calls,
        "calls_today": calls_today,
        "calls_this_week": calls_this_week,
        "calls_this_month": calls_this_month,
        "completed_calls": completed_calls,
        "pending_calls": pending_calls,
        "failed_calls": failed_calls,
        "successful_calls_today": successful_calls_today,
        "calls_by_day": calls_by_day,
        "transfers_by_day": transfers_by_day,
        "calls_by_status": calls_by_status,
        "total_reports": total_reports,
        "alerts_count": alerts_count,
        "success_rate_today": (
            round((successful_calls_today / calls_today * 100), 2) if calls_today > 0 else 0
        ),
        "joignabilite_7j": (
            round((completed_calls_week / calls_this_week * 100), 1) if calls_this_week > 0 else 0
        ),
        "completed_calls_week": completed_calls_week,
        "time_saved_seconds": time_saved_seconds,
        "transfers_count": transfers_count,
        "callbacks_needed": callbacks_needed,
    }


@router.get("/chart", response_model=Dict[str, Any])
async def get_dashboard_chart(
    period: Literal["7d", "30d", "90d", "1y"] = Query(default="7d"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Données du graphique pour une période donnée (7d / 30d / 90d / 1y)."""

    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if period == "30d":
        n_days, group_by = 30, "day"
    elif period == "90d":
        n_days, group_by = 90, "week"
    elif period == "1y":
        n_days, group_by = 365, "month"
    else:  # 7d
        n_days, group_by = 7, "day"

    start = today - timedelta(days=n_days - 1)

    if group_by == "day":
        bucket_expr = func.date(Call.created_at).label("bucket")
    else:
        bucket_expr = func.date_trunc(group_by, Call.created_at).label("bucket")

    calls_stmt = (
        select(bucket_expr, func.count(Call.id).label("count"))
        .where(Call.created_at >= start)
        .group_by(bucket_expr)
        .order_by(bucket_expr)
    )
    alerts_stmt = (
        select(bucket_expr, func.count(Call.id).label("count"))
        .where(
            Call.created_at >= start,
            Call.call_metadata["alert_triggered"].astext == "true",
        )
        .group_by(bucket_expr)
        .order_by(bucket_expr)
    )

    def _key(bucket) -> str:
        """Normalise le bucket en chaîne YYYY-MM-DD."""
        if hasattr(bucket, "date"):
            return bucket.date().isoformat()
        return str(bucket)

    calls_result  = await db.execute(calls_stmt)
    alerts_result = await db.execute(alerts_stmt)
    calls_dict  = {_key(r.bucket): r.count for r in calls_result}
    alerts_dict = {_key(r.bucket): r.count for r in alerts_result}

    # Génère tous les buckets pour combler les jours/semaines/mois vides
    points: List[Dict] = []

    if group_by == "day":
        for i in range(n_days):
            d = (today - timedelta(days=n_days - 1 - i)).date()
            k = d.isoformat()
            points.append({"date": k, "calls": calls_dict.get(k, 0), "alerts": alerts_dict.get(k, 0)})

    elif group_by == "week":
        # Première semaine = lundi de la semaine contenant `start`
        d = start.date() - timedelta(days=start.date().weekday())
        end = today.date()
        while d <= end:
            k = d.isoformat()
            points.append({"date": k, "calls": calls_dict.get(k, 0), "alerts": alerts_dict.get(k, 0)})
            d += timedelta(weeks=1)

    elif group_by == "month":
        d = start.date().replace(day=1)
        end = today.date().replace(day=1)
        while d <= end:
            k = d.isoformat()
            points.append({"date": k, "calls": calls_dict.get(k, 0), "alerts": alerts_dict.get(k, 0)})
            d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)  # prochain mois

    return {"points": points, "period": period}
