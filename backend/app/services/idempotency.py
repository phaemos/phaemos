"""
Idempotency-Key for the creates that would double on a retry.

A client that timed out on `POST /devices` cannot tell whether the machine was made. Sent again it makes a second machine with a
second key. With an `Idempotency-Key` header the first answer is kept for 24 hours and a repeat of the same request gets that answer
back (with `Idempotent-Replayed: true`) and creates nothing.

  where        Redis (the same store as the repeat windows), under phaemos:idem:<caller id>:<route>:<key>, with the process memory
               as the fallback when Redis is down. It lives 24 hours and is not kept longer
  per caller   the key is scoped to the signed-in account and the route, so one account's key can never replay or collide with
               another's and the same key on another route is a different request
  same body    the stored answer and status come back. Nothing is created
  other body   422 idempotency_key_reused. A key names one request
  still running  409 idempotency_in_progress, for a repeat that arrives while the first is being handled
  at rest      the stored answer can hold a device key (shown only once), so it is encrypted with a key derived for this purpose
               (services/keys.py, purpose "idempotency") and a copy of the database or of Redis cannot read it. A 4xx or 5xx is
               never stored: a failed create may be tried again with the same key
A request with no header is handled as before.
"""

import hashlib
import json
import threading
import time

from cryptography.fernet import Fernet, InvalidToken
from fastapi.responses import JSONResponse

from app.errors import ApiError, Code
from app.services import cooldown
from app.services.keys import fernet_keys

TTL_SECONDS = 24 * 3600
MAX_KEY_LENGTH = 128
MIN_KEY_LENGTH = 8
_PREFIX = "phaemos:idem"
_lock = threading.Lock()
_local: dict[str, tuple[float, str]] = {}


def _fernet() -> Fernet:
    return Fernet(fernet_keys("idempotency")[0])


def _store_get(key: str) -> str | None:
    if cooldown._redis_usable():
        try:
            value = cooldown._client().get(key)
            return value.decode() if isinstance(value, bytes) else value
        except Exception:  # noqa: BLE001
            cooldown._redis_failed()
    with _lock:
        item = _local.get(key)
        if item and item[0] > time.monotonic():
            return item[1]
        _local.pop(key, None)
    return None


def _store_set(key: str, value: str, nx: bool = False) -> bool:
    if cooldown._redis_usable():
        try:
            return bool(cooldown._client().set(key, value, nx=nx, ex=TTL_SECONDS))
        except Exception:  # noqa: BLE001
            cooldown._redis_failed()
    with _lock:
        item = _local.get(key)
        if nx and item and item[0] > time.monotonic():
            return False
        _local[key] = (time.monotonic() + TTL_SECONDS, value)
        return True


def _store_delete(key: str) -> None:
    if cooldown._redis_usable():
        try:
            cooldown._client().delete(key)
            return
        except Exception:  # noqa: BLE001
            cooldown._redis_failed()
    with _lock:
        _local.pop(key, None)


def reset() -> None:
    """Forget everything held in process memory. For tests."""
    with _lock:
        _local.clear()


class Idempotency:
    """One request's view of its key. `replay` is the answer to send back when this is a repeat, else None."""

    def __init__(self, store_key: str | None, body_hash: str | None, replay: JSONResponse | None = None):
        self.store_key = store_key
        self.body_hash = body_hash
        self.replay = replay

    def save(self, status_code: int, body) -> None:
        """Keep the success answer for the key. A failure is never kept, so the client may try again with the same key."""
        if self.store_key is None:
            return
        if status_code >= 400:
            _store_delete(self.store_key)
            return
        sealed = _fernet().encrypt(json.dumps({"hash": self.body_hash, "status": status_code, "body": body}, default=str).encode()).decode()
        _store_set(self.store_key, "done:" + sealed)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        # an error while handling the request frees the key, so the client may try again with it
        if exc_type is not None:
            self.abandon()
        return False

    def abandon(self) -> None:
        """Free the key after an error, so the client may try again."""
        if self.store_key is not None:
            _store_delete(self.store_key)


def begin(caller_id, route: str, header_value: str | None, payload) -> Idempotency:
    """
    Look the key up. None of this runs without the header. `payload` is the request body as a Pydantic model or a dict.
    """
    if header_value is None:
        return Idempotency(None, None)
    key = header_value.strip()
    if not MIN_KEY_LENGTH <= len(key) <= MAX_KEY_LENGTH or not key.isprintable() or any(c.isspace() for c in key):
        raise ApiError(
            422, Code.VALIDATION_FAILED,
            f"Idempotency-Key must be {MIN_KEY_LENGTH} to {MAX_KEY_LENGTH} visible characters, for example a random UUID",
        )
    data = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    body_hash = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
    store_key = f"{_PREFIX}:{caller_id}:{route}:{hashlib.sha256(key.encode()).hexdigest()}"
    # the first request takes the key. A later one finds it
    if _store_set(store_key, "pending:" + body_hash, nx=True):
        return Idempotency(store_key, body_hash)
    held = _store_get(store_key)
    if held is None:
        # it expired between the two calls: take it
        if _store_set(store_key, "pending:" + body_hash, nx=True):
            return Idempotency(store_key, body_hash)
        held = _store_get(store_key) or ""
    if held.startswith("pending:"):
        if held[len("pending:"):] != body_hash:
            raise ApiError(422, Code.IDEMPOTENCY_KEY_REUSED, "This Idempotency-Key was used with a different request. Use a new key for a new request")
        raise ApiError(409, Code.IDEMPOTENCY_IN_PROGRESS, "The first request with this Idempotency-Key is still being handled. Wait a moment and send it again", headers={"Retry-After": "2"})
    try:
        stored = json.loads(_fernet().decrypt(held[len("done:"):].encode()))
    except (InvalidToken, ValueError):
        # a stored answer that cannot be read (the key changed) is treated as gone: the request is handled again
        _store_delete(store_key)
        return begin(caller_id, route, header_value, payload)
    if stored["hash"] != body_hash:
        raise ApiError(422, Code.IDEMPOTENCY_KEY_REUSED, "This Idempotency-Key was used with a different request. Use a new key for a new request")
    return Idempotency(store_key, body_hash, JSONResponse(
        status_code=stored["status"], content=stored["body"], headers={"Idempotent-Replayed": "true"},
    ))
