"""
WebSocket route - clients connect here to receive live telemetry pushes
for a specific device without polling.
"""

import uuid

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query

from app.db import SessionLocal
from app.routes.auth import decode_token, user_for_token
from app.services.ws_manager import subscribe, unsubscribe

router = APIRouter()


@router.websocket("/ws/telemetry/{device_id}")
async def telemetry_ws(
    websocket: WebSocket,
    device_id: uuid.UUID,
    token: str | None = Query(default=None),
):
    # validate the JWT before calling accept() so unauthenticated clients are
    # rejected at the handshake stage and never enter the subscriber list.
    # close code 1008 (Policy Violation) is the standard signal for auth failure.
    if not token:
        await websocket.close(code=1008)
        return

    # only a live access token opens the feed. Refresh, invite and sign-in
    # challenge tokens are refused, as are tokens from a session that has ended.
    db = SessionLocal()
    try:
        user_for_token(db, decode_token(token, "access"))
    except HTTPException:
        await websocket.close(code=1008)
        return
    finally:
        db.close()

    await websocket.accept()
    key = str(device_id)
    subscribe(key, websocket)
    try:
        # keep the connection alive - the client does not need to send messages,
        # but we must await receive to detect disconnects.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        unsubscribe(key, websocket)
