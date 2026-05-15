# Build stage
FROM python:3.12-slim as builder

# Installer les dépendances système pour la compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    build-essential \
    libpq-dev \
    libffi-dev \
    libssl-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Créer un environnement virtuel
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copier les fichiers de requirements
COPY requirements.txt .

# Installer les dépendances Python
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Runtime stage
FROM python:3.12-slim

# Installer les dépendances runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    ffmpeg \
    sox \
    libsox-fmt-all \
    curl \
    espeak \
    espeak-data \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Créer un utilisateur non-root
RUN useradd -m -u 1000 -s /bin/bash appuser

# Copier l'environnement virtuel depuis le builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Définir le répertoire de travail
WORKDIR /app

# Copier le code de l'application
COPY --chown=appuser:appuser . .

# Copier et rendre exécutable le script d'initialisation
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Créer les répertoires nécessaires (y compris pour les modèles Piper TTS)
RUN mkdir -p /app/logs /app/recordings /app/reports /app/temp /app/models/piper && \
    chown -R appuser:appuser /app

# Variables d'environnement
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Exposer le port
EXPOSE 8000

# Utiliser l'entrypoint pour initialiser les répertoires
ENTRYPOINT ["/entrypoint.sh"]

# Commande par défaut
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

