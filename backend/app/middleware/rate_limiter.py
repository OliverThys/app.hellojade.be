"""
Middleware de rate limiting pour protéger les endpoints critiques
"""
from typing import Callable, Optional

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings


class RateLimiter:
    """
    Rate limiter simple basé sur la mémoire (pour production, utiliser Redis)
    
    Note: Pour la production, il faudrait utiliser slowapi avec Redis
    """
    
    def __init__(self):
        self.requests = {}  # {ip: [timestamps]}
        self.blocked_ips = {}  # {ip: unblock_time}
    
    def is_allowed(
        self,
        ip: str,
        limit: int = 60,
        window_seconds: int = 60,
    ) -> tuple[bool, Optional[int]]:
        """
        Vérifie si une requête est autorisée
        
        Args:
            ip: Adresse IP
            limit: Nombre maximum de requêtes
            window_seconds: Fenêtre de temps en secondes
        
        Returns:
            Tuple (is_allowed, retry_after_seconds)
        """
        from datetime import datetime, timedelta
        
        now = datetime.now()
        
        # Vérifier si l'IP est bloquée
        if ip in self.blocked_ips:
            unblock_time = self.blocked_ips[ip]
            if now < unblock_time:
                retry_after = int((unblock_time - now).total_seconds())
                return False, retry_after
            else:
                # Débloquer
                del self.blocked_ips[ip]
        
        # Nettoyer les anciennes requêtes
        if ip in self.requests:
            cutoff = now - timedelta(seconds=window_seconds)
            self.requests[ip] = [
                ts for ts in self.requests[ip] if ts > cutoff
            ]
        else:
            self.requests[ip] = []
        
        # Vérifier la limite
        if len(self.requests[ip]) >= limit:
            # Bloquer pour window_seconds
            self.blocked_ips[ip] = now + timedelta(seconds=window_seconds)
            return False, window_seconds
        
        # Ajouter la requête actuelle
        self.requests[ip].append(now)
        
        return True, None
    
    def reset_attempts(self, ip: str):
        """Réinitialise les tentatives pour une IP"""
        if ip in self.requests:
            del self.requests[ip]
        if ip in self.blocked_ips:
            del self.blocked_ips[ip]


# Instance globale du rate limiter
rate_limiter = RateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware de rate limiting pour FastAPI
    """
    
    def __init__(self, app, enabled: bool = True):
        super().__init__(app)
        self.enabled = enabled
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Intercepter les requêtes et appliquer le rate limiting"""
        
        if not self.enabled or not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)
        
        # Ignorer les endpoints de health check et metrics
        if request.url.path in ["/health", "/ready", "/metrics", "/metrics/custom"]:
            return await call_next(request)
        
        # Obtenir l'IP du client
        client_ip = request.client.host if request.client else "unknown"
        
        # Vérifier les headers de proxy
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        
        # Appliquer le rate limiting général
        limit = settings.RATE_LIMIT_PER_MINUTE
        is_allowed, retry_after = rate_limiter.is_allowed(
            ip=client_ip,
            limit=limit,
            window_seconds=60,
        )
        
        if not is_allowed:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "detail": "Trop de requêtes. Veuillez réessayer plus tard.",
                    "retry_after": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after) if retry_after else "60",
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )
        
        # Compter les requêtes restantes
        remaining = limit - len(rate_limiter.requests.get(client_ip, []))
        
        # Exécuter la requête
        response = await call_next(request)
        
        # Ajouter les headers de rate limiting
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))
        
        return response


# Rate limiter spécifique pour le login
class LoginRateLimiter:
    """Rate limiter spécialisé pour les tentatives de connexion"""
    
    def __init__(self):
        self.attempts = {}  # {ip: [timestamps]}
        self.blocked = {}  # {ip: unblock_time}
    
    def is_allowed(
        self,
        ip: str,
        max_attempts: int = 5,
        window_minutes: int = 15,
    ) -> tuple[bool, Optional[int]]:
        """
        Vérifie si une tentative de connexion est autorisée
        
        Args:
            ip: Adresse IP
            max_attempts: Nombre maximum de tentatives
            window_minutes: Fenêtre de temps en minutes
        
        Returns:
            Tuple (is_allowed, retry_after_minutes)
        """
        from datetime import datetime, timedelta
        
        now = datetime.now()
        
        # Vérifier si l'IP est bloquée
        if ip in self.blocked:
            unblock_time = self.blocked[ip]
            if now < unblock_time:
                retry_after = int((unblock_time - now).total_seconds() / 60)
                return False, retry_after
            else:
                # Débloquer et réinitialiser
                del self.blocked[ip]
                if ip in self.attempts:
                    del self.attempts[ip]
        
        # Nettoyer les anciennes tentatives
        if ip in self.attempts:
            cutoff = now - timedelta(minutes=window_minutes)
            self.attempts[ip] = [
                ts for ts in self.attempts[ip] if ts > cutoff
            ]
        else:
            self.attempts[ip] = []
        
        # Vérifier la limite
        if len(self.attempts[ip]) >= max_attempts:
            # Bloquer pour window_minutes
            self.blocked[ip] = now + timedelta(minutes=window_minutes)
            return False, window_minutes
        
        return True, None
    
    def record_failed_attempt(self, ip: str):
        """Enregistre une tentative de connexion échouée"""
        from datetime import datetime
        if ip not in self.attempts:
            self.attempts[ip] = []
        self.attempts[ip].append(datetime.now())
    
    def is_login_allowed(
        self,
        ip: str,
        max_attempts: int = 5,
        window_minutes: int = 15,
    ) -> tuple[bool, Optional[int]]:
        """Alias pour is_allowed pour compatibilité"""
        return self.is_allowed(ip, max_attempts, window_minutes)
    
    def reset_attempts(self, ip: str):
        """Réinitialise les tentatives (après connexion réussie)"""
        if ip in self.attempts:
            del self.attempts[ip]
        if ip in self.blocked:
            del self.blocked[ip]
    
    def reset_all(self):
        """Réinitialise toutes les tentatives (pour admin)"""
        self.attempts.clear()
        self.blocked.clear()


# Instance globale pour le login
login_rate_limiter = LoginRateLimiter()

