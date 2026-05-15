"""
Métriques Prometheus personnalisées pour HelloJADE

Ce module expose des métriques métier spécifiques à l'application.
"""
from prometheus_client import Counter, Histogram, Gauge
from prometheus_client import CollectorRegistry, REGISTRY

# Créer un registre de métriques personnalisé
CUSTOM_REGISTRY = CollectorRegistry()

# Métriques d'appels
calls_total = Counter(
    'hellojadeapp_calls_total',
    'Nombre total d\'appels',
    ['status', 'patient_id'],
    registry=CUSTOM_REGISTRY
)

call_duration = Histogram(
    'hellojadeapp_call_duration_seconds',
    'Durée des appels en secondes',
    ['status'],
    buckets=(5, 10, 30, 60, 120, 300, 600),
    registry=CUSTOM_REGISTRY
)

# Métriques de transcription
transcription_total = Counter(
    'hellojadeapp_transcriptions_total',
    'Nombre total de transcriptions',
    ['status', 'language'],
    registry=CUSTOM_REGISTRY
)

transcription_duration = Histogram(
    'hellojadeapp_transcription_duration_seconds',
    'Durée de transcription en secondes',
    buckets=(10, 30, 60, 120, 300),
    registry=CUSTOM_REGISTRY
)

transcription_confidence = Histogram(
    'hellojadeapp_transcription_confidence',
    'Confiance de transcription (0-1)',
    buckets=(0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0),
    registry=CUSTOM_REGISTRY
)

# Métriques d'analyse IA
ai_analysis_total = Counter(
    'hellojadeapp_ai_analyses_total',
    'Nombre total d\'analyses IA',
    ['status', 'model'],
    registry=CUSTOM_REGISTRY
)

ai_analysis_duration = Histogram(
    'hellojadeapp_ai_analysis_duration_seconds',
    'Durée d\'analyse IA en secondes',
    ['model'],
    buckets=(5, 10, 15, 30, 60, 120),
    registry=CUSTOM_REGISTRY
)

# Métriques de patients
patients_total = Gauge(
    'hellojadeapp_patients_total',
    'Nombre total de patients',
    ['status'],
    registry=CUSTOM_REGISTRY
)

patients_high_risk = Gauge(
    'hellojadeapp_patients_high_risk',
    'Nombre de patients à risque élevé (score >= 7)',
    registry=CUSTOM_REGISTRY
)

# Métriques de rapports
reports_total = Counter(
    'hellojadeapp_reports_total',
    'Nombre total de rapports générés',
    ['type'],
    registry=CUSTOM_REGISTRY
)

report_generation_duration = Histogram(
    'hellojadeapp_report_generation_duration_seconds',
    'Durée de génération de rapport en secondes',
    buckets=(1, 2, 5, 10, 30),
    registry=CUSTOM_REGISTRY
)

# Métriques d'authentification
auth_attempts_total = Counter(
    'hellojadeapp_auth_attempts_total',
    'Nombre total de tentatives d\'authentification',
    ['result'],  # success, failure
    registry=CUSTOM_REGISTRY
)

# Métriques Celery
celery_tasks_total = Counter(
    'hellojadeapp_celery_tasks_total',
    'Nombre total de tâches Celery',
    ['task_name', 'status'],  # success, failure
    registry=CUSTOM_REGISTRY
)

celery_task_duration = Histogram(
    'hellojadeapp_celery_task_duration_seconds',
    'Durée d\'exécution des tâches Celery en secondes',
    ['task_name'],
    buckets=(1, 5, 10, 30, 60, 300, 600),
    registry=CUSTOM_REGISTRY
)

celery_queue_length = Gauge(
    'hellojadeapp_celery_queue_length',
    'Longueur de la queue Celery',
    ['queue_name'],
    registry=CUSTOM_REGISTRY
)

# Métriques de cache Redis
cache_operations_total = Counter(
    'hellojadeapp_cache_operations_total',
    'Nombre total d\'opérations de cache',
    ['operation', 'result'],  # operation: get, set, delete | result: hit, miss, error, success
    registry=CUSTOM_REGISTRY
)

cache_duration = Histogram(
    'hellojadeapp_cache_duration_seconds',
    'Durée des opérations de cache en secondes',
    ['operation'],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
    registry=CUSTOM_REGISTRY
)

cache_size = Gauge(
    'hellojadeapp_cache_size_bytes',
    'Taille du cache en octets',
    ['cache_type'],  # questions, analyses, etc.
    registry=CUSTOM_REGISTRY
)

cache_enabled = Gauge(
    'hellojadeapp_cache_enabled',
    'État du cache (1 = activé, 0 = désactivé)',
    registry=CUSTOM_REGISTRY
)

