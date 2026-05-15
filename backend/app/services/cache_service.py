"""
Service de cache Redis pour optimiser les performances.

Utilise Redis pour mettre en cache:
- Questions du questionnaire
- Analyses (hash de transcription)
- Autres données fréquemment accédées
"""
import json
import hashlib
import time
from typing import Any, Dict, List, Optional
import asyncio

import redis
from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import (
    cache_operations_total,
    cache_duration,
    cache_enabled,
)

logger = get_logger(__name__)


class CacheService:
    """
    Service de cache Redis avec fallback gracieux.
    
    Si Redis n'est pas disponible, le cache est désactivé silencieusement.
    Utilise redis synchrone avec asyncio.to_thread pour les opérations async.
    """
    
    def __init__(self):
        self._redis: Optional[redis.Redis] = None
        self._enabled = False
        self._connection_error = False
        
    def _get_redis(self) -> Optional[redis.Redis]:
        """Obtient ou crée la connexion Redis (synchrone)."""
        if self._connection_error:
            return None
            
        if self._redis is None:
            try:
                # Utiliser REDIS_URL si disponible, sinon construire depuis les settings
                import os
                redis_url = os.getenv("REDIS_URL")
                if not redis_url:
                    # Construire l'URL Redis
                    password = settings.REDIS_PASSWORD
                    # Dans Docker, utiliser "redis" comme host, sinon localhost
                    redis_host = "redis" if os.path.exists("/.dockerenv") else settings.REDIS_HOST
                    if password:
                        redis_url = f"redis://:{password}@{redis_host}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
                    else:
                        redis_url = f"redis://{redis_host}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
                
                self._redis = redis.from_url(
                    redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                
                # Tester la connexion
                self._redis.ping()
                self._enabled = True
                cache_enabled.set(1)
                logger.info("Cache Redis activé")
                
            except Exception as e:
                logger.warning(f"Cache Redis non disponible: {e}. Cache désactivé.")
                self._connection_error = True
                self._enabled = False
                cache_enabled.set(0)
                return None
                
        return self._redis
    
    async def get(self, key: str) -> Optional[Any]:
        """Récupère une valeur du cache."""
        start_time = time.time()
        redis_client = self._get_redis()
        if not redis_client:
            cache_operations_total.labels(operation="get", result="miss").inc()
            return None
            
        try:
            value = await asyncio.to_thread(redis_client.get, key)
            duration = time.time() - start_time
            cache_duration.labels(operation="get").observe(duration)
            
            if value:
                cache_operations_total.labels(operation="get", result="hit").inc()
                return json.loads(value)
            else:
                cache_operations_total.labels(operation="get", result="miss").inc()
        except Exception as e:
            cache_operations_total.labels(operation="get", result="error").inc()
            logger.warning(f"Erreur lecture cache Redis: {e}")
            
        return None
    
    async def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        """Stocke une valeur dans le cache avec TTL."""
        start_time = time.time()
        redis_client = self._get_redis()
        if not redis_client:
            cache_operations_total.labels(operation="set", result="error").inc()
            return False
            
        try:
            await asyncio.to_thread(
                redis_client.setex,
                key,
                ttl,
                json.dumps(value, default=str)
            )
            duration = time.time() - start_time
            cache_duration.labels(operation="set").observe(duration)
            cache_operations_total.labels(operation="set", result="success").inc()
            return True
        except Exception as e:
            cache_operations_total.labels(operation="set", result="error").inc()
            logger.warning(f"Erreur écriture cache Redis: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Supprime une clé du cache."""
        start_time = time.time()
        redis_client = self._get_redis()
        if not redis_client:
            cache_operations_total.labels(operation="delete", result="error").inc()
            return False
            
        try:
            await asyncio.to_thread(redis_client.delete, key)
            duration = time.time() - start_time
            cache_duration.labels(operation="delete").observe(duration)
            cache_operations_total.labels(operation="delete", result="success").inc()
            return True
        except Exception as e:
            cache_operations_total.labels(operation="delete", result="error").inc()
            logger.warning(f"Erreur suppression cache Redis: {e}")
            return False
    
    async def delete_pattern(self, pattern: str) -> int:
        """Supprime toutes les clés correspondant au pattern."""
        redis_client = self._get_redis()
        if not redis_client:
            return 0
            
        try:
            keys = await asyncio.to_thread(redis_client.keys, pattern)
            if keys:
                return await asyncio.to_thread(redis_client.delete, *keys)
            return 0
        except Exception as e:
            logger.warning(f"Erreur suppression pattern cache Redis: {e}")
            return 0
    
    def is_enabled(self) -> bool:
        """Vérifie si le cache est activé."""
        return self._enabled


# Instance globale du service de cache
cache_service = CacheService()


def cache_key_hash(data: str) -> str:
    """Génère un hash MD5 pour une clé de cache."""
    return hashlib.md5(data.encode()).hexdigest()

