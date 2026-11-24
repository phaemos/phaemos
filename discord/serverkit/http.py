"""A small Discord REST client: rate limits, retries and an audit log reason on every change."""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

DEFAULT_BASE = "https://discord.com/api/v10"
LOCAL_HOSTS = ("localhost", "127.0.0.1")
REASON_LIMIT = 512
_ID = re.compile(r"\d{5,}")


_LONG_TOKEN = re.compile(r"[A-Za-z0-9_\-.]{24,}")


def _mask(text: str) -> str:
    """Keeps the words of an error and drops anything that could be an id or a secret."""
    return _LONG_TOKEN.sub("[masked]", _ID.sub("[id]", text))


def error_detail(payload: object) -> str:
    """Discord's own account of a refused form: each field path with its code and message.

    A 400 carries "errors", a tree whose leaves hold "_errors" lists of {code, message}. The paths name the
    field. A message may quote a value, so ids and long tokens are masked before anything is printed.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("errors"), dict):
        return ""
    found: list[str] = []

    def walk(node: object, path: list[str]) -> None:
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if key == "_errors" and isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        where = ".".join(path) or "request"
                        found.append(f"{where}: {item.get('code', '?')}: {_mask(str(item.get('message', '')))}")
            else:
                walk(value, [*path, str(key)])

    walk(payload["errors"], [])
    return "; ".join(found)[:600]


class ApiError(Exception):
    def __init__(self, status: int, code: int | None, message: str, method: str, path: str):
        self.status = status
        self.code = code
        self.message = message
        self.method = method
        self.route = route_label(path)
        super().__init__(f"{method} {self.route} answered {status}: {message}")


class AuthError(ApiError):
    pass


class Fatal(Exception):
    """The run must stop at once: a refusal that more tries cannot cure."""


class MaxWaitExceeded(Fatal):
    pass


class ReadOnly(Exception):
    """A write was attempted in a mode that must not change anything."""


def route_label(path: str) -> str:
    """The path with every id removed, so errors and logs never carry one."""
    return _ID.sub(":id", path.split("?")[0])


def resolve_base(value: str | None) -> str:
    if not value:
        return DEFAULT_BASE
    host = urllib.parse.urlparse(value).hostname
    if host not in LOCAL_HOSTS:
        raise ValueError("DISCORD_API_BASE is only for tests and must point at localhost or 127.0.0.1")
    return value.rstrip("/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: the bot token travels in the Authorization header and a redirect could carry it away."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


@dataclass
class _Bucket:
    remaining: int
    reset_at: float


class Client:
    def __init__(
        self,
        base: str,
        token: str,
        user_agent: str,
        *,
        max_wait: float = 900,
        read_only: bool = False,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        timeout: float = 30,
    ):
        self._base = base.rstrip("/")
        self._token = token
        self._user_agent = user_agent
        self.max_wait = max_wait
        self.read_only = read_only
        self._sleep = sleep
        self._clock = clock
        self._timeout = timeout
        self.waited = 0.0
        self._bucket_of: dict[str, str] = {}
        self._buckets: dict[str, _Bucket] = {}
        self._global_until = 0.0
        self._forbidden = 0
        self.writes = 0

    # waiting -----------------------------------------------------------------------------------

    def _wait(self, seconds: float) -> None:
        if seconds <= 0:
            return
        if self.waited + seconds > self.max_wait:
            raise MaxWaitExceeded(f"stopped: waiting for rate limits would pass {self.max_wait:g} seconds")
        self.waited += seconds
        self._sleep(seconds)

    @staticmethod
    def _key(method: str, path: str) -> tuple[str, str]:
        ids = _ID.findall(path)
        major = ids[0] if ids else ""
        template = _ID.sub(":id", path.split("?")[0])
        return f"{method} {template}", major

    def _before(self, key: str, major: str) -> None:
        now = self._clock()
        if self._global_until > now:
            self._wait(self._global_until - now)
        bucket_id = self._bucket_of.get(key)
        if bucket_id:
            bucket = self._buckets.get(f"{bucket_id}:{major}")
            if bucket and bucket.remaining <= 0:
                now = self._clock()
                if bucket.reset_at > now:
                    # the reset time is rounded, so a small margin keeps the request from arriving a hair early
                    self._wait(bucket.reset_at - now + 0.05)

    def _after(self, key: str, major: str, headers) -> None:
        bucket_id = headers.get("X-RateLimit-Bucket")
        if not bucket_id:
            return
        self._bucket_of[key] = bucket_id
        remaining = headers.get("X-RateLimit-Remaining")
        reset_after = headers.get("X-RateLimit-Reset-After")
        if remaining is not None and reset_after is not None:
            self._buckets[f"{bucket_id}:{major}"] = _Bucket(int(remaining), self._clock() + float(reset_after))

    # one request -------------------------------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        body=None,
        *,
        reason: str | None = None,
        recheck: Callable[[], object | None] | None = None,
        files: list[tuple[str, bytes]] | None = None,
    ):
        """Send a request and return the decoded answer.

        `recheck` is for creates. After a server error or a dropped connection the create may still
        have happened, so the list is read again and the object returned when it is there.
        """
        if method != "GET":
            if self.read_only:
                raise ReadOnly(f"{method} {route_label(path)} refused in a read only run")
            if not reason:
                raise ValueError(f"{method} {route_label(path)} needs an audit log reason")
        key, major = self._key(method, path)
        server_failures = 0
        rate_limited = 0
        while True:
            self._before(key, major)
            try:
                status, headers, payload = self._send(method, path, body, reason, files)
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
                status, headers, payload = 599, {}, {"message": f"network error: {type(exc).__name__}"}
            self._after(key, major, headers)
            if 300 <= status < 400:
                message = "Discord sent a redirect, which is never followed so the token stays put"
                raise ApiError(status, None, message, method, path)
            if status < 400:
                if method != "GET":
                    self.writes += 1
                return payload
            message = payload.get("message", "") if isinstance(payload, dict) else str(payload)[:200]
            code = payload.get("code") if isinstance(payload, dict) else None
            if status == 429:
                rate_limited += 1
                if rate_limited > 5:
                    raise ApiError(status, code, "still rate limited after five tries", method, path)
                retry = float(headers.get("Retry-After") or payload.get("retry_after") or 1)
                if payload.get("global") or headers.get("X-RateLimit-Global"):
                    self._global_until = self._clock() + retry
                self._wait(retry + random.uniform(0.05, 0.25))
                continue
            if status >= 500:
                server_failures += 1
                if server_failures > 3:
                    raise ApiError(status, code, message or "server error", method, path)
                self._wait(2 ** (server_failures - 1))
                if recheck is not None and method == "POST":
                    existing = recheck()
                    if existing is not None:
                        return existing
                continue
            if status == 401:
                raise AuthError(status, code, "the token was refused", method, path)
            if status == 403:
                self._forbidden += 1
                if self._forbidden >= 3:
                    raise Fatal("stopped: three refusals for missing permission in one run")
            if status == 400:
                detail = error_detail(payload)
                if detail:
                    message = f"{message} [{detail}]"
            raise ApiError(status, code, message, method, path)

    def _send(self, method: str, path: str, body, reason: str | None, files=None):
        content_type = "application/json"
        if files:
            data, content_type = multipart(body, files)
        else:
            data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self._base + path, data=data, method=method)
        request.add_header("Authorization", f"Bot {self._token}")
        request.add_header("User-Agent", self._user_agent)
        if data is not None or method in ("POST", "PUT", "PATCH"):
            request.add_header("Content-Type", content_type)
        if reason:
            request.add_header("X-Audit-Log-Reason", urllib.parse.quote(reason[:REASON_LIMIT], safe=" "))
        try:
            with _OPENER.open(request, timeout=self._timeout) as response:
                return response.status, response.headers, _decode(response.read())
        except urllib.error.HTTPError as err:
            return err.code, err.headers, _decode(err.read())


def multipart(body, files: list[tuple[str, bytes]]) -> tuple[bytes, str]:
    """A multipart/form-data body: the JSON as `payload_json` and each file as `files[n]`.

    From the Uploading Files section: "Each file parameter must be uniquely named in the format files[n]" and
    every one "must include a valid Content-Disposition subpart header with a filename".
    """
    boundary = "serverkit" + hashlib.sha256(json.dumps(body).encode()).hexdigest()[:24]
    out = bytearray()
    out += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
        "Content-Type: application/json\r\n\r\n"
    ).encode()
    out += json.dumps(body).encode() + b"\r\n"
    for index, (filename, content) in enumerate(files):
        out += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="files[{index}]"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        out += content + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def _decode(raw: bytes):
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return {"message": raw[:200].decode("utf-8", "replace")}
