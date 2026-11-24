import ipaddress
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from .counter import ReplayCounter, state_dir

Reading = dict[str, Any]

# the most of any reply that is read, so a hostile or broken server cannot use up memory
MAX_REPLY_BYTES = 1024 * 1024
# the whole request must end within this many seconds. The time-out passed to httpx applies to each
# socket operation, so a server that drips bytes would never trip it
DEADLINE_SECONDS = 30.0


# retries: a read is tried again after a network failure and after 502, 503 and 504 (up to MAX_TRIES tries,
# waiting 0.5 s, 1 s, 2 s). A 429 waits for Retry-After (DEFAULT_RETRY_AFTER when absent) for any
# method, up to
# MAX_429_WAITS times and a wait longer than MAX_RETRY_AFTER is not waited out. A write is otherwise only
# retried when the caller marks it idempotent.
MAX_TRIES = 4
MAX_429_WAITS = 3
MAX_RETRY_AFTER = 60.0
DEFAULT_RETRY_AFTER = 10.0
BACKOFF_BASE = 0.5
BACKOFF_CAP = 8.0
DEFAULT_LIST_LIMIT = 1000
MAX_PAGE = 200
MAX_LIST_LIMIT = 100_000


@dataclass
class Page:
    """Everything a pager collected. total is the server's X-Total-Count or None."""

    items: list[dict[str, Any]]
    total: int | None
    more: bool
    next_before: str | None = None


class ReplyTooLarge(Exception):
    """The reply was longer than MAX_REPLY_BYTES."""


_TOKEN_SHAPE = re.compile(r"pht_[A-Za-z0-9_\-]+")


class ApiError(httpx.HTTPStatusError):
    """The API answered with a status of 300 or more.

    status is the HTTP status. code is the API's stable error code (a snake_case word) when the reply
    carried one, otherwise an empty string: read the code when there is one and the status when there is
    not and never match on the message. message is the server's own words with anything shaped like a
    token blanked. retry_after is the seconds the server asked for on a 429 or None.
    """

    def __init__(
        self,
        message: str,
        *,
        request: httpx.Request,
        response: httpx.Response,
        code: str = "",
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, request=request, response=response)
        self.status = response.status_code
        self.code = code
        self.message = message
        self.retry_after = retry_after


class ReplayRefused(ApiError):
    """The API answered 409: this post's boot and seq are not newer than the last it accepted. If the
    state folder was wiped an admin can accept a new counter for the device."""


def _parse_error(data: bytes) -> tuple[str, str]:
    """The readable message and the stable code from an error body: {"code", "detail", "errors": [...]} or the
    older {"detail": ...} where detail may be a list."""
    try:
        body = json.loads(data)
    except ValueError:
        return _TOKEN_SHAPE.sub("<token>", data.decode("utf-8", "replace")[:200]), ""
    if not isinstance(body, dict):
        return "", ""
    message, code = "", str(body.get("code") or "")
    detail = body.get("detail")
    errors = body.get("errors")
    if isinstance(detail, str):
        message = detail
    elif isinstance(detail, list):
        errors = detail
    if isinstance(errors, list):
        parts = []
        for item in errors:
            if isinstance(item, dict):
                where = ".".join(str(x) for x in item.get("loc", []))
                parts.append(f"{where}: {item.get('msg', '')}" if where else str(item.get("msg", "")))
        if parts:
            message = f"{message}: {'; '.join(parts)}" if message else "; ".join(parts)
    clean = "".join(ch if ch.isprintable() else " " for ch in _TOKEN_SHAPE.sub("<token>", message))
    return clean[:200], re.sub(r"[^a-z0-9_]", "", code.lower())[:64]


# the exit codes of phaemosctl, so a script reads the same meaning from either tool
EXIT_FAILURE, EXIT_USAGE, EXIT_NOT_SIGNED_IN, EXIT_FORBIDDEN, EXIT_NOT_FOUND = 1, 2, 3, 4, 5
EXIT_CONFLICT, EXIT_RATE_LIMITED, EXIT_UNAVAILABLE = 6, 7, 8


def exit_code(status: int) -> int:
    """The exit code a status maps to: 3 not signed in, 4 not allowed, 5 not found, 6 conflict or invalid,
    7 rate limited, 8 the server failed, 1 anything else."""
    if status == 401:
        return EXIT_NOT_SIGNED_IN
    if status == 403:
        return EXIT_FORBIDDEN
    if status == 404:
        return EXIT_NOT_FOUND
    if status in (400, 409, 422):
        return EXIT_CONFLICT
    if status == 429:
        return EXIT_RATE_LIMITED
    if status >= 500 or status == 408:
        return EXIT_UNAVAILABLE
    return EXIT_FAILURE


def error_line(error: ApiError) -> str:
    """One line a person can act on, with the server's own message."""
    text = error.message or f"status {error.status}"
    if error.status == 401:
        return f"the credential was refused: {text}"
    if error.status == 429 and error.retry_after:
        return f"rate limited: {text} (the server asked for {error.retry_after:g} s)"
    return text


def is_duplicate(reply: dict[str, Any]) -> bool:
    """True when the API already has this exact post (200, status duplicate, nothing stored)."""
    return reply.get("status") == "duplicate" and reply.get("stored") is False


def is_local_host(host: str) -> bool:
    """True for the name localhost and literal loopback addresses, where plain HTTP does not cross a
    network. Any other name, including one ending in .localhost, is not resolved here and so is not known
    to be local."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_base_url(url: str, allow_insecure_http: bool = False) -> str:
    """Return the address without a trailing slash. Raises ValueError for a bad one.

    https:// is always accepted. http:// is accepted for a loopback address. For any other
    host it is accepted only when allow_insecure_http is set, because it sends the device key and the readings
    across the network unencrypted.
    """
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("the API address must be an http:// or https:// address with a host")
    if parts.username or parts.password:
        raise ValueError("the API address must not hold a user name or password")
    # the server answers 404 for a path with a trailing slash and never redirects it, so the address is the
    # base only and the client adds each route itself
    if parts.path.strip("/") or parts.query:
        raise ValueError(
            "the API address must be the base address only, for example https://api.example.org: "
            f"remove the path {parts.path!r} (the client adds each route itself)"
        )
    if parts.scheme == "http" and not is_local_host(parts.hostname) and not allow_insecure_http:
        raise ValueError(
            "the API address is plain http:// to a host that is not local, which sends the key and the "
            "readings unencrypted. Use https:// or allow plain HTTP for bench testing only"
        )
    return url.rstrip("/")


class PhaemosClient:
    """Thin wrapper over the PHAEMOS HTTP API.

    Telemetry ingest authenticates with a device API key in the X-API-Key header.
    Account routes use the session cookie set by login.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 10.0,
        allow_insecure_http: bool = False,
        replay: bool = True,
        state_directory: Path | None = None,
        deadline: float = DEADLINE_SECONDS,
        token: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # the device key and the access token are kept apart: the key goes only to the ingest route and the
        # token (pht_...) to everything else and never both on one request
        self._key = api_key
        self._token = token
        self._sleep = sleep
        headers: dict[str, str] = {}
        # certificates are checked (verify=True is httpx's default, stated so it is not switched off by
        # accident) and redirects are not followed, so the key is never sent to another address
        self._http = httpx.Client(
            base_url=check_base_url(base_url, allow_insecure_http),
            headers=headers,
            timeout=timeout,
            verify=True,
            follow_redirects=False,
        )
        self._deadline = deadline
        # a device key means readings are posted, so they carry boot, seq and up
        self.counter: ReplayCounter | None = None
        if api_key and replay:
            self.counter = ReplayCounter(api_key, state_directory if state_directory else state_dir())

    def status(self) -> dict[str, Any]:
        return self._request("GET", "/status")

    def create_device(self, name: str, location: str, device_type: str) -> dict[str, Any]:
        """Register a device. It needs an API token of the admin scope. The answer holds the key once."""
        body = {"name": name, "location": location, "type": device_type}
        return self._request("POST", "/api/v1/devices", body)

    def send_reading(self, reading: Reading) -> dict[str, Any]:
        """Post one reading. It is stamped with boot, seq and up unless it already carries a pair. Raises
        ReplayRefused on a 409. A reply for which is_duplicate is true was delivered earlier. It is never
        retried."""
        if self.counter is not None:
            reading = self.counter.stamp(reading)
        return self._request("POST", "/api/v1/telemetry", reading, use_key=True)

    # ---- reads with an access token ----

    def whoami(self) -> dict[str, Any]:
        """Who the token is: id, role, signed_in_with and, for a token, its id, name, scope and expiry."""
        return self._request("GET", "/api/v1/auth/whoami")

    def health_summary(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/health/summary")

    def ml_status(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/ml/status")

    def list_devices(
        self,
        name: str | None = None,
        search: str | None = None,
        status: str | None = None,
        tag: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> Page:
        """Devices. name is an exact match that ignores case and search a contains match."""
        params = {
            k: v for k, v in {"name": name, "search": search, "status": status, "tag": tag}.items() if v
        }
        return self._paged("/api/v1/devices", params, limit)

    def get_device(self, device_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/devices/{device_id}")

    def list_alerts(
        self,
        device_id: str | None = None,
        resolved: bool | None = None,
        category: str | None = None,
        severity: str | None = None,
        kind: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> Page:
        """Alerts. Every filter is the server's own."""
        params: dict[str, Any] = {}
        if resolved is not None:
            params["resolved"] = str(resolved).lower()
        for key, value in {
            "device_id": device_id,
            "category": category,
            "severity": severity,
            "kind": kind,
        }.items():
            if value:
                params[key] = value
        return self._paged("/api/v1/alerts", params, limit)

    def get_alert(self, alert_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/alerts/{alert_id}")

    def list_windows(self, limit: int = DEFAULT_LIST_LIMIT) -> Page:
        return self._paged("/api/v1/maintenance-windows", {}, limit)

    def list_tokens(self) -> list[dict[str, Any]]:
        """The account's unrevoked API tokens, newest first. A token may read the list, never change it."""
        items, _ = self._call("GET", "/api/v1/tokens")
        if not isinstance(items, list):
            raise ValueError("the reply is not a list")
        return items

    def resolve_alert(self, alert_id: str) -> dict[str, Any]:
        """Resolve an alert. It needs a token of the operate scope. Repeating it is safe, so it is retried."""
        return self._request("POST", f"/api/v1/alerts/{alert_id}/resolve", idempotent=True)

    def list_tickets(
        self,
        status: str | None = None,
        priority: str | None = None,
        alert_id: str | None = None,
        device_id: str | None = None,
        ticket_number: int | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> Page:
        params: dict[str, Any] = {
            k: v
            for k, v in {
                "status": status,
                "priority": priority,
                "alert_id": alert_id,
                "device_id": device_id,
            }.items()
            if v
        }
        if ticket_number:
            params["ticket_number"] = ticket_number
        return self._paged("/api/v1/tickets", params, limit)

    def get_ticket(self, ticket_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/tickets/{ticket_id}")

    def latest_reading(self, device_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/telemetry/{device_id}/latest")

    def readings_page(
        self,
        device_id: str,
        limit: int = 100,
        before: str | None = None,
        from_ts: str | None = None,
        to_ts: str | None = None,
    ) -> Page:
        """One page of raw readings, newest first. The route sends no total, on purpose. A full page carries
        the cursor of its last row in next_before: pass it back as before until a page comes back short."""
        params: dict[str, Any] = {"limit": limit}
        if before:
            params["before"] = before
        if from_ts:
            params["from"] = from_ts
        if to_ts:
            params["to"] = to_ts
        items, headers = self._call("GET", f"/api/v1/telemetry/{device_id}", params=params)
        if not isinstance(items, list):
            raise ValueError("the reply is not a list")
        return Page(items, None, bool(headers.get("X-Next-Before")), headers.get("X-Next-Before") or None)

    def readings(
        self,
        device_id: str,
        limit: int = 100,
        before: str | None = None,
        from_ts: str | None = None,
        to_ts: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.readings_page(device_id, limit, before, from_ts, to_ts).items

    def export_csv(self, device_id: str, from_ts: str, destination: Path, to_ts: str | None = None) -> int:
        """Stream a machine's readings (at most 31 days) to a file, as the server sends them and return the
        bytes written. The file is not replaced if it exists and a failed export leaves no file."""
        params = {"device_id": device_id, "from_ts": from_ts}
        if to_ts:
            params["to_ts"] = to_ts
        destination = Path(destination)
        written = 0
        ends = time.monotonic() + max(self._deadline, 600.0)
        headers = self._auth_headers(False)
        with self._http.stream("GET", "/api/v1/telemetry/export", params=params, headers=headers) as response:
            response.raise_for_status()
            with open(destination, "xb") as handle:
                try:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
                        written += len(chunk)
                        if time.monotonic() > ends:
                            raise TimeoutError("the export took too long")
                except BaseException:
                    handle.close()
                    destination.unlink(missing_ok=True)
                    raise
        return written

    def _paged(self, path: str, params: dict[str, Any], limit: int) -> Page:
        """Page through a list route. Where the server sends X-Next-Before the walk uses that keyset
        cursor (read straight off an index however far back). Otherwise it uses offset and skip is sent
        too because a route that has not moved to the one contract still reads skip. A route that ignores
        paging stops the walk."""
        if not 1 <= limit <= MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIST_LIMIT}")
        items: list[dict[str, Any]] = []
        total: int | None = None
        cursor: str | None = None
        while len(items) < limit:
            want = min(limit - len(items), MAX_PAGE)
            query: dict[str, Any] = {**params, "limit": want}
            if cursor:
                query["before"] = cursor
            else:
                query["offset"] = len(items)
                query["skip"] = len(items)
            page, headers = self._call("GET", path, params=query)
            if not isinstance(page, list):
                raise ValueError("the reply is not a list")
            if items and page and page[0] == items[0]:
                raise ValueError(f"{path} ignored its paging parameters (it sent the same page twice)")
            if headers.get("X-Total-Count", "").isdigit():
                total = int(headers["X-Total-Count"])
            items.extend(page)
            if len(page) > want or len(page) < want:
                break
            if headers.get("X-Next-Before"):
                cursor = headers["X-Next-Before"]
                continue
            if total is not None and len(items) >= total:
                break
        more = total > len(items) if total is not None and not cursor else len(items) >= limit
        return Page(items, total, more)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "PhaemosClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _auth_headers(self, use_key: bool) -> dict[str, str]:
        if use_key:
            return {"X-API-Key": self._key} if self._key else {}
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def _request(
        self, method: str, path: str, body: Any = None, use_key: bool = False, idempotent: bool = False
    ) -> dict[str, Any]:
        parsed, _ = self._call(
            method, path, body=body, use_key=use_key, idempotent=idempotent, retry=not use_key
        )
        if not isinstance(parsed, dict):
            raise ValueError("the reply is not a JSON object")
        return parsed

    def _call(
        self,
        method: str,
        path: str,
        body: Any = None,
        params: dict[str, Any] | None = None,
        use_key: bool = False,
        idempotent: bool = False,
        retry: bool = True,
    ) -> tuple[Any, httpx.Headers]:
        """Send a request with the retry rules and read the reply as a stream: at most MAX_REPLY_BYTES and
        within the deadline."""
        tries = waits = 0
        while True:
            try:
                return self._once(method, path, body, params, use_key)
            except (httpx.TransportError, httpx.HTTPStatusError) as error:
                status = error.response.status_code if isinstance(error, httpx.HTTPStatusError) else 0
                if not retry or isinstance(error, ReplayRefused):
                    raise
                can_repeat = method == "GET" or idempotent
                if isinstance(error, httpx.HTTPStatusError) and status == 429:
                    wait = _retry_after(error.response.headers.get("Retry-After"))
                    if waits >= MAX_429_WAITS or wait > MAX_RETRY_AFTER:
                        raise
                    waits += 1
                elif (status == 0 or status in (502, 503, 504)) and can_repeat and tries + 1 < MAX_TRIES:
                    if isinstance(error, httpx.TransportError) and _is_certificate_error(error):
                        raise
                    wait = min(BACKOFF_BASE * 2**tries, BACKOFF_CAP)
                    tries += 1
                else:
                    raise
                self._sleep(wait)

    def _once(
        self, method: str, path: str, body: Any, params: dict[str, Any] | None, use_key: bool
    ) -> tuple[Any, httpx.Headers]:
        ends = time.monotonic() + self._deadline
        with self._http.stream(
            method, path, json=body, params=params, headers=self._auth_headers(use_key)
        ) as response:
            data = bytearray()
            # no chunk size: a size makes httpx hold bytes back until it has that many. A drip
            # would then never reach the deadline check below
            for chunk in response.iter_bytes():
                data += chunk
                if len(data) > MAX_REPLY_BYTES:
                    raise ReplyTooLarge(f"the reply is longer than {MAX_REPLY_BYTES} bytes")
                if time.monotonic() > ends:
                    raise TimeoutError(f"the reply took longer than {self._deadline:g} seconds")
            if response.status_code >= 300:
                message, code = _parse_error(bytes(data))
                for secret in (self._key, self._token):
                    if secret:
                        message = message.replace(secret, "<secret>")
                wait: float | None = None
                if response.headers.get("Retry-After", "").isdigit():
                    wait = float(response.headers["Retry-After"])
                if response.status_code == 409 and use_key:
                    raise ReplayRefused(
                        "the API refused this post's boot and seq as older than the last it accepted (409): "
                        "if the state folder was wiped an admin can accept a new counter",
                        request=response.request,
                        response=response,
                        code=code,
                        retry_after=wait,
                    )
                raise ApiError(
                    f"{response.status_code} {message}".strip(),
                    request=response.request,
                    response=response,
                    code=code,
                    retry_after=wait,
                )
            headers = response.headers
        if not data:
            return {}, headers
        return json.loads(bytes(data)), headers


def _retry_after(value: str | None) -> float:
    try:
        return float(int(str(value).strip()))
    except ValueError:
        return DEFAULT_RETRY_AFTER


def _is_certificate_error(error: Exception) -> bool:
    text = f"{type(error).__name__} {error}".lower()
    return "certificate" in text or "ssl" in text
