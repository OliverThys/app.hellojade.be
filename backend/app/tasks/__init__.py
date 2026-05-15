"""
Configuration Celery pour HelloJADE

Ce module configure Celery pour le traitement asynchrone des tâches.
"""
from celery import Celery

from app.core.config import settings

# Créer l'instance Celery
celery_app = Celery(
    "hellojadeapp",
    broker=str(settings.CELERY_BROKER_URL),
    backend=str(settings.CELERY_RESULT_BACKEND),
    include=[
        "app.tasks.report_tasks",
        "app.tasks.scheduler_tasks",
    ],
)

# Configuration Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Brussels",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes max
    task_soft_time_limit=25 * 60,  # 25 minutes soft limit
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    task_acks_late=True,
    worker_disable_rate_limits=False,
)

# Scheduler Celery Beat
celery_app.conf.beat_schedule = {
    # Appels planifiés automatiques — toutes les 5 minutes
    "process-pending-calls": {
        "task": "app.tasks.scheduler_tasks.process_pending_calls",
        "schedule": 300.0,  # 5 minutes
        "options": {"expires": 240},  # expire si pas traité dans les 4 min
    },
    # Génération automatique de rapports
    "generate-pending-reports": {
        "task": "app.tasks.report_tasks.generate_pending_reports",
        "schedule": 3600.0,  # Toutes les heures
        "options": {"expires": 3600},
    },
}
