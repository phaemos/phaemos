"""
Small ASGI middleware that applies to every request.

SourceMiddleware  records where the request came from, for the sign-in guard.
NulGuard          refuses a request whose text holds a NUL character, which PostgreSQL cannot store and which
                  surfaced as a 500 (and, at sign-in, told a known address from an unknown one).
SecurityHeaders   adds nosniff to every reply and no-store to the account routes, which carry tokens.
"""

import json
import logging
import time

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.limiter import _trusted, normalise_address
from app import request_id
from app.services import signin_guard, token_access

# the one route exempt from the NUL check, by its exact method and path. A machine's reading is never lost because one string in
# it is bad: the ingest path cleans those fields itself, drops the bad one, names it in `quality` and keeps the reading. Every route
# a person or a browser calls keeps the check. Nothing else a machine calls has a body (the firmware routes are GETs with a key in a
# header), so nothing else is exempt. A new entry here needs the same reason
EXEMPT = frozenset({("POST", "/api/v1/telemetry"), ("POST", "/api/v1/telemetry/batch")})

# bodies larger than this are not read here. Every JSON route is far below it. A firmware upload is multipart and skipped
_MAX_BODY_TO_CHECK = 1_000_000


def _client_source(scope: Scope) -> str:
    client = scope.get("client")
    peer = client[0] if client else "unknown"
    if _trusted(peer):
        real_ip = Headers(scope=scope).get("x-real-ip", "").strip()
        if real_ip:
            return normalise_address(real_ip)
    return normalise_address(peer)


_request_log = logging.getLogger("app.request")
# probes that run every few seconds would drown the log. Everything else is logged once
_UNLOGGED_PATHS = frozenset({"/", "/livez", "/readyz", "/metrics"})


class RequestIdMiddleware:
    """Give every request an id, return it as X-Request-ID and make it available to the handlers and the log.

    `request.state.request_id` holds it. An id the client sent is used only when it is 8 to 64 characters of letters, digits,
    dot, underscore and hyphen, so it is safe to log. Anything else is replaced by a fresh one.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        offered = Headers(scope=scope).get(request_id.HEADER)
        rid = request_id.accept_or_make(offered)
        scope.setdefault("state", {})["request_id"] = rid
        token = request_id.request_id_var.set(rid)
        started = time.monotonic()
        status = {"code": 500}

        async def with_header(message: Message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                headers = MutableHeaders(scope=message)
                headers[request_id.HEADER] = rid
            await send(message)

        try:
            await self.app(scope, receive, with_header)
        finally:
            if scope["type"] == "http" and scope.get("path") not in _UNLOGGED_PATHS:
                # one line for the request: the path only (never the query string, which can hold a token) and no header. The
                # id is added by the log format
                _request_log.info(
                    "%s %s -> %s in %d ms", scope.get("method", "-"), scope.get("path", "-"), status["code"],
                    (time.monotonic() - started) * 1000,
                )
            request_id.request_id_var.reset(token)


class SourceMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] in ("http", "websocket"):
            token = signin_guard.current_source.set(_client_source(scope))
            caller = token_access.current_token.set({})
            try:
                await self.app(scope, receive, send)
            finally:
                token_access.current_token.reset(caller)
                signin_guard.current_source.reset(token)
            return
        await self.app(scope, receive, send)


def _has_nul(data: bytes) -> bool:
    # a raw NUL or the JSON escape \u0000 in any case. A literal backslash then u0000 is refused too, which is harmless
    return b"\x00" in data or b"\\u0000" in data.lower()


class NulGuard:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if (scope["method"], scope.get("path", "")) in EXEMPT:
            await self.app(scope, receive, send)
            return
        if _has_nul(scope.get("query_string", b"")) or b"%00" in scope.get("query_string", b"").lower():
            await self._refuse(scope, receive, send)
            return
        headers = Headers(scope=scope)
        ctype = headers.get("content-type", "")
        length = headers.get("content-length")
        if (
            scope["method"] in ("POST", "PUT", "PATCH", "DELETE")
            and "multipart/" not in ctype
            and length is not None and length.isdigit() and 0 < int(length) <= _MAX_BODY_TO_CHECK
        ):
            chunks, more = [], True
            while more:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunks.append(message.get("body", b""))
                more = message.get("more_body", False)
            body = b"".join(chunks)
            if _has_nul(body):
                await self._refuse(scope, receive, send)
                return
            replayed = False

            async def replay() -> Message:
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            await self.app(scope, replay, send)
            return
        await self.app(scope, receive, send)

    async def _refuse(self, scope: Scope, receive: Receive, send: Send):
        body = json.dumps({
            "code": "nul_character", "detail": "Text must not contain NUL characters",
            "request_id": scope.get("state", {}).get("request_id"),
        }).encode()
        await send({"type": "http.response.start", "status": 422,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


class SecurityHeaders:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")

        async def wrapped(message: Message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                if path.startswith("/api/v1/auth"):
                    # replies here carry tokens, so no cache or proxy may keep them
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, wrapped)
