"""
Endpoints WebSocket pour les communications temps réel
"""
import json
from typing import Dict, Set

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database import get_db
from app.dependencies import get_optional_current_user

router = APIRouter()
logger = get_logger(__name__)


class ConnectionManager:
    """Gestionnaire des connexions WebSocket"""
    
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, user_id: str):
        """Connecter un client WebSocket"""
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        self.active_connections[user_id].add(websocket)
        logger.info(f"WebSocket connected for user {user_id}")
    
    def disconnect(self, websocket: WebSocket, user_id: str):
        """Déconnecter un client WebSocket"""
        if user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        logger.info(f"WebSocket disconnected for user {user_id}")
    
    async def send_personal_message(self, message: str, user_id: str):
        """Envoyer un message à un utilisateur spécifique"""
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                await connection.send_text(message)
    
    async def broadcast(self, message: str):
        """Diffuser un message à tous les utilisateurs connectés"""
        for connections in self.active_connections.values():
            for connection in connections:
                await connection.send_text(message)


manager = ConnectionManager()


@router.websocket("/connect")
async def websocket_endpoint(
    websocket: WebSocket,
    db: AsyncSession = Depends(get_db),
):
    """
    Endpoint WebSocket pour les notifications temps réel

    Messages supportés:
    - call_status: Mise à jour du statut d'un appel
    - patient_alert: Alerte patient critique
    - analysis_complete: Analyse IA terminée
    """

    # TODO: Authentifier via token dans les headers ou query params
    user_id = "anonymous"  # Temporaire

    await manager.connect(websocket, user_id)

    # Envoyer un message de confirmation de connexion
    await websocket.send_text(json.dumps({
        "type": "connected",
        "payload": {
            "status": "connected",
            "user_id": user_id,
            "timestamp": json.dumps({"type": "datetime"})  # Sera géré par le logger
        }
    }))

    try:
        while True:
            # Recevoir un message du client
            data = await websocket.receive_text()

            try:
                message = json.loads(data)
                event_type = message.get("type")
                payload = message.get("payload", {})

                # Traiter selon le type d'événement
                if event_type == "ping":
                    # Répondre au ping
                    await websocket.send_text(json.dumps({"type": "pong"}))

                elif event_type == "subscribe":
                    # S'abonner à des événements spécifiques
                    channel = payload.get("channel")
                    logger.info(f"User {user_id} subscribed to {channel}")
                    # Confirmer la souscription
                    await websocket.send_text(json.dumps({
                        "type": "subscribed",
                        "payload": {"channel": channel}
                    }))

                else:
                    # Echo pour debug
                    await websocket.send_text(f"Echo: {data}")

            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Invalid JSON"
                }))

    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
        logger.info(f"WebSocket client {user_id} disconnected")


async def notify_call_status_update(call_id: str, status: str, duration: int | None = None):
    """Notifier une mise à jour du statut d'un appel"""
    payload = {
        "call_id": call_id,
        "status": status,
    }
    if duration is not None:
        payload["duration"] = duration
    
    message = json.dumps({
        "type": "call_status",
        "payload": payload,
    })
    await manager.broadcast(message)
    logger.debug(f"📡 WebSocket notification sent: call_id={call_id}, status={status}, duration={duration}")


async def notify_patient_alert(patient_id: str, alert: Dict):
    """Notifier une alerte patient"""
    message = json.dumps({
        "type": "patient_alert",
        "payload": {
            "patient_id": patient_id,
            "alert": alert,
        }
    })
    await manager.broadcast(message)

