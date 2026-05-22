"""
WebSocket Manager — keeps track of connected dashboard clients per device
and broadcasts new telemetry readings to them.

Lives in services/ (not routes/) so both the ws route and the telemetry
route can import it without creating a circular import.

Note: uses a simple in-memory dict. Works correctly for a single-worker
deployment. A multi-worker setup would require a Redis pub/sub broker here.
"""

import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# device_id (str) → list of active WebSocket connections for that device.
_connections: dict[str, list[WebSocket]] = defaultdict(list)


def subscribe(device_id: str, ws: WebSocket) -> None:
    """Register a WebSocket client for a given device."""
    _connections[device_id].append(ws)


def unsubscribe(device_id: str, ws: WebSocket) -> None:
    """Remove a WebSocket client (called on disconnect)."""
    try:
        _connections[device_id].remove(ws)
    except ValueError:
        pass  # already removed, nothing to do


async def broadcast(device_id: str, data: str) -> None:
    """Send a JSON string to every client watching this device.
    Dead connections are cleaned up automatically."""
    dead: list[WebSocket] = []
    for ws in list(_connections[device_id]):
        try:
            await ws.send_text(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        unsubscribe(device_id, ws)
