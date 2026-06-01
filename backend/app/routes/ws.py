"""
WebSocket route - clients connect here to receive live telemetry pushes
for a specific device without polling.
"""

import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from jose import JWTError

from app.config import settings
from app.services.ws_manager import subscribe, unsubscribe

router = APIRouter()


@router.websocket("/ws/telemetry/{device_id}")
async def telemetry_ws(
    websocket: WebSocket,
    device_id: uuid.UUID,
    token: str | None = Query(default=None),
):
    # I validate the JWT before calling accept() so unauthenticated clients are
    # rejected at the handshake stage and never enter the subscriber list.
    # Close code 1008 (Policy Violation) is the standard signal for auth failure.
    if not token:
        await websocket.close(code=1008)
        return

    try:
        from jose import jwt
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        if not payload.get("sub"):
            raise JWTError
    except JWTError:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    key = str(device_id)
    subscribe(key, websocket)
    try:
        # Keep the connection alive - the client does not need to send messages,
        # but we must await receive to detect disconnects.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        unsubscribe(key, websocket)
