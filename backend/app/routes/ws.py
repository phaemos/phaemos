"""
WebSocket route — clients connect here to receive live telemetry pushes
for a specific device without polling.
"""

import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.ws_manager import subscribe, unsubscribe

router = APIRouter()


@router.websocket("/ws/telemetry/{device_id}")
async def telemetry_ws(websocket: WebSocket, device_id: uuid.UUID):
    # Accept the upgrade request and register this client.
    await websocket.accept()
    key = str(device_id)
    subscribe(key, websocket)
    try:
        # Keep the connection alive — the client doesn't need to send messages,
        # but we must await receive to detect disconnects.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        unsubscribe(key, websocket)
