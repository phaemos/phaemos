"""
WebSocket route - clients connect here to receive live telemetry pushes
for a specific device without polling.
"""

import asyncio
import json
import logging
import time
import uuid

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.db import SessionLocal
from app.limiter import _trusted, normalise_address
from app.models.device import Device
from app.routes.auth import decode_token, user_for_token
from app.services.access import can_read_device
from app.services.ws_manager import subscribe, unsubscribe

router = APIRouter()
logger = logging.getLogger(__name__)

# how often an open socket asks again whether its user may still watch the machine;
# a password change, a role change or a machine changing hands is therefore noticed within
# this many seconds. A module value so tests can shorten it.
RECHECK_SECONDS = 60

# how long a client that sent no token in the URL has to send its first frame. The most
# that frame may hold is the second number. A real one is {"type":"auth","token":"..."}, well under a kilobyte.
FIRST_FRAME_SECONDS = 5
FIRST_FRAME_MAX_CHARS = 4096

# the URL form is kept so the dashboard does not break before it sends the frame. It is logged once
_warned_about_url_token = False

# live sockets held now, by account and by address, so one caller cannot hold them all;
# one process serves the API, so plain counters are enough.
_by_user: dict[str, int] = {}
_by_address: dict[str, int] = {}

# every refusal closes with this code: bad token, missing machine and refused machine alike
_POLICY_VIOLATION = 1008


def _authorise(token: str | None, device_id: uuid.UUID) -> tuple[float, str] | None:
    """Return the token's expiry (seconds since the epoch) and the account id when it may watch the machine.

    Returns None for every refusal so the caller cannot tell the cases apart. Blocking
    database work, so callers run it in a thread. Only a live access token from a session
    that has not ended opens the feed. Refresh, invite and sign-in challenge tokens are
    refused. The role and the machine's owner are read fresh each time.
    """
    if not token:
        return None
    db = SessionLocal()
    try:
        payload = decode_token(token, "access")
        user = user_for_token(db, payload)
        device = db.query(Device).filter(Device.id == device_id).first()
        if device is None or not can_read_device(user, device):
            return None
        return float(payload.get("exp", 0)), str(user.id)
    except HTTPException:
        return None
    finally:
        db.close()


def _client_address(websocket: WebSocket) -> str:
    # the same rule as the rate limiter: X-Real-IP counts only when the peer is the trusted proxy
    peer = websocket.client.host if websocket.client else "unknown"
    if _trusted(peer):
        real_ip = websocket.headers.get("x-real-ip", "").strip()
        if real_ip:
            return normalise_address(real_ip)
    return normalise_address(peer)


def _take(counts: dict[str, int], key: str, most: int) -> bool:
    if counts.get(key, 0) >= most:
        return False
    counts[key] = counts.get(key, 0) + 1
    return True


def _release(counts: dict[str, int], key: str) -> None:
    left = counts.get(key, 0) - 1
    if left > 0:
        counts[key] = left
    else:
        counts.pop(key, None)


async def _close_quietly(websocket: WebSocket) -> None:
    try:
        await websocket.close(code=_POLICY_VIOLATION)
    except Exception:  # noqa: BLE001
        pass  # the client has already gone


async def _drain(websocket: WebSocket) -> None:
    # the client has nothing to say after its first frame, but a receive is needed to notice a
    # disconnect. Anything larger than the auth frame ends the socket, so it cannot be used to
    # make the server read and hold big messages for as long as it stays open.
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            if len(message.get("text") or message.get("bytes") or "") > FIRST_FRAME_MAX_CHARS:
                await _close_quietly(websocket)
                return
    except (WebSocketDisconnect, RuntimeError):
        return


async def _watch(websocket: WebSocket, token: str, device_id: uuid.UUID, expires_at: float) -> None:
    """Close the socket when its token expires or the answer to _authorise changes."""
    while True:
        wait = min(RECHECK_SECONDS, expires_at - time.time())
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            still_allowed = time.time() < expires_at and await run_in_threadpool(_authorise, token, device_id) is not None
        except Exception:  # noqa: BLE001
            # a failed check ends the feed rather than leaving it open unchecked
            still_allowed = False
        if not still_allowed:
            await _close_quietly(websocket)
            return


async def _token_from_first_frame(websocket: WebSocket) -> str | None:
    """Wait for {"type":"auth","token":"..."} and return the token. Anything else gives None.

    A timeout, a frame that is not text, one that is too long, bad JSON and the wrong shape
    all give None. The caller closes the socket the same way as for any other refusal.
    """
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=FIRST_FRAME_SECONDS)
    except Exception:  # noqa: BLE001
        # a timeout, a disconnect or a binary frame
        return None
    # uvicorn is started with --ws-max-size so nothing much larger than this is ever read. This
    # check also covers a server started without it and no part of a long frame is parsed
    if len(raw) > FIRST_FRAME_MAX_CHARS:
        return None
    try:
        frame = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(frame, dict) or frame.get("type") != "auth":
        return None
    token = frame.get("token")
    return token if isinstance(token, str) and token else None


@router.websocket("/ws/telemetry/{device_id}")
async def telemetry_ws(
    websocket: WebSocket,
    device_id: uuid.UUID,
    token: str | None = Query(default=None),
):
    global _warned_about_url_token
    held: list[tuple[dict[str, int], str]] = []
    try:
        # one address cannot hold more than its share, counted before anything is read from it
        address = _client_address(websocket)
        if not _take(_by_address, address, settings.ws_max_per_address):
            await websocket.accept()
            await _close_quietly(websocket)
            return
        held.append((_by_address, address))

        if token:
            # the older form: the token is in the URL, which proxies and logs may record
            if not settings.ws_token_in_url_allowed:
                await websocket.accept()
                await _close_quietly(websocket)
                return
            if not _warned_about_url_token:
                _warned_about_url_token = True
                logger.warning("a websocket client sent its token in the URL. Send it in the first message instead")
            auth = await run_in_threadpool(_authorise, token, device_id)
            await websocket.accept()
        else:
            # the better form: accept, then read the token from the first frame so it never appears in a URL
            await websocket.accept()
            token = await _token_from_first_frame(websocket)
            auth = await run_in_threadpool(_authorise, token, device_id) if token else None

        # a refused client is closed at once with 1008, so a browser sees the documented close
        # code and not a bare failed handshake. It is never subscribed and is sent nothing, so
        # nothing about the machine is revealed. Every refusal looks the same.
        if auth is None:
            await _close_quietly(websocket)
            return
        expires_at, user_id = auth
        if not _take(_by_user, user_id, settings.ws_max_per_user):
            await _close_quietly(websocket)
            return
        held.append((_by_user, user_id))

        key = str(device_id)
        subscribe(key, websocket)
        receiving = asyncio.ensure_future(_drain(websocket))
        watching = asyncio.ensure_future(_watch(websocket, token, device_id, expires_at))
        try:
            await asyncio.wait({receiving, watching}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            receiving.cancel()
            watching.cancel()
            unsubscribe(key, websocket)
    finally:
        for counts, owner in held:
            _release(counts, owner)
