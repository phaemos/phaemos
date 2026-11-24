"""
One shape for every error the API sends and the codes that go in it.

Every non-2xx answer is JSON:

    {"code": "device_not_found", "detail": "No such device", "request_id": "..."}

`detail` is always a sentence for a person and `code` is stable, snake_case and part of the contract: a client reads the
code and never matches the sentence. Request validation adds `errors`, a list of {"loc", "msg", "type"}.

Raise an error like this:

    raise ApiError(404, Code.DEVICE_NOT_FOUND, "No such device")

An `HTTPException` raised the old way still comes out in this shape, with a code taken from its status (`not_found`,
`conflict`...), so the API never shows two shapes while routes are moved over. A route that has been moved uses `ApiError`
and a code from `Code`. The walking test fails a route that still raises `HTTPException` in its own code.
"""

import logging
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings

logger = logging.getLogger(__name__)


class Code:
    """Every error code. One code, one situation: add a new one rather than reuse a code for something else."""

    # ── generic, used when a status has no more specific code ───────────────
    BAD_REQUEST = "bad_request"
    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    CONFLICT = "conflict"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    UNPROCESSABLE = "unprocessable"
    RATE_LIMITED = "rate_limited"
    INTERNAL_ERROR = "internal_error"
    NOT_IMPLEMENTED = "not_implemented"
    BAD_GATEWAY = "bad_gateway"
    UNAVAILABLE = "unavailable"
    GATEWAY_TIMEOUT = "gateway_timeout"
    DATABASE_ERROR = "database_error"

    # ── request validation ──────────────────────────────────────────────────
    VALIDATION_FAILED = "validation_failed"          # the body, query or path did not fit. `errors` says where
    NUL_CHARACTER = "nul_character"                  # text holding a NUL character, refused before it reaches a handler
    INVALID_FILTER = "invalid_filter"                # a filter value that is not one of the allowed values
    INVALID_RANGE = "invalid_range"                  # a time range or window that is reversed or too wide
    BODY_TOO_LARGE = "body_too_large"                # a body over the route's cap

    # ── credentials and sessions ────────────────────────────────────────────
    TOKEN_INVALID = "token_invalid"                  # a bearer token that is unknown, malformed, expired or revoked
    SESSION_ENDED = "session_ended"                  # the session or its access token is no longer valid
    REFRESH_MISSING = "refresh_missing"              # no refresh cookie was sent
    SIGN_IN_AGAIN = "sign_in_again"                  # a two-step step whose challenge is gone or has expired
    INVALID_CREDENTIALS = "invalid_credentials"      # a wrong password, an unknown address or an account that cannot sign in
    ORIGIN_NOT_ALLOWED = "origin_not_allowed"        # a cookie route called from a page on another origin
    DEVICE_KEY_INVALID = "device_key_invalid"        # an unknown or revoked device key
    ACCOUNT_DISABLED = "account_disabled"            # the account is deactivated
    SESSION_REQUIRED = "session_required"            # a route a token may never call. Sign in with a session
    SCOPE_TOO_LOW = "scope_too_low"                  # the API token's scope does not allow this method or route
    ADMIN_REQUIRED = "admin_required"                # the route is for admins
    REGISTRATION_CLOSED = "registration_closed"
    PROVIDER_NOT_CONFIGURED = "provider_not_configured"
    PROVIDER_ERROR = "provider_error"                # the sign-in provider answered with an error
    PROVIDER_LINK_REFUSED = "provider_link_refused"
    PROVIDER_ALREADY_LINKED = "provider_already_linked"
    EMAIL_FROM_PROVIDER = "email_from_provider"      # the email comes from the sign-in provider and cannot change here
    EMAIL_IN_USE = "email_in_use"                    # the address is already registered
    OAUTH_STATE_INVALID = "oauth_state_invalid"      # the provider return was not started in this browser or has expired

    # ── proof of ownership ──────────────────────────────────────────────────
    PROOF_REQUIRED = "proof_required"                # a password is needed and was not sent
    PROOF_WRONG = "proof_wrong"                      # the password or code sent is wrong
    CODE_REQUIRED = "code_required"                  # a two-step code is needed and was not sent
    PROVIDER_PROOF_REQUIRED = "provider_proof_required"   # sign in through the provider again, within 5 minutes
    PROOF_RATE_LIMITED = "proof_rate_limited"        # too many proofs in a minute
    NO_PASSWORD = "no_password"                      # the account has no password
    PASSWORD_WRONG = "password_wrong"                # the current password given to change it is wrong

    # ── two-step ────────────────────────────────────────────────────────────
    TWO_STEP_ALREADY_ON = "two_step_already_on"
    TWO_STEP_NOT_ON = "two_step_not_on"
    TWO_STEP_NOT_STARTED = "two_step_not_started"    # confirm was called before enable
    TWO_STEP_CODE_WRONG = "two_step_code_wrong"

    # ── accounts and administration ─────────────────────────────────────────
    USER_NOT_FOUND = "user_not_found"
    SESSION_NOT_FOUND = "session_not_found"
    SELF_ACTION_REFUSED = "self_action_refused"      # an admin acting on their own account where that is refused
    LAST_ADMIN = "last_admin"
    ACCOUNT_DEACTIVATED = "account_deactivated"      # the target account is deactivated
    OWNS_MACHINES = "owns_machines"                  # hand the account's machines to someone first
    RESET_LINK_INVALID = "reset_link_invalid"
    RESET_LINK_RECENT = "reset_link_recent"          # one was sent a moment ago
    EMAIL_NOT_SENT = "email_not_sent"
    EMAIL_CHANGES_LIMIT = "email_changes_limit"
    INVITATION_NOT_FOUND = "invitation_not_found"
    INVITATION_INVALID = "invitation_invalid"        # unknown, expired or cancelled
    INVITATION_USED = "invitation_used"
    ACCOUNT_EXISTS = "account_exists"
    SERVICE_ACCOUNT_REFUSED = "service_account_refused"   # a service account cannot do this (sign in, change a password...)
    EXPORT_FAILED = "export_failed"

    # ── API tokens ──────────────────────────────────────────────────────────
    TOKEN_NOT_FOUND = "token_not_found"
    NO_TOKEN_IN_USE = "no_token_in_use"              # DELETE /tokens/current from a session, which has no API token
    TOKEN_LIMIT = "token_limit"                      # 20 live tokens already
    TOKEN_SCOPE_FORBIDDEN = "token_scope_forbidden"  # an admin token asked for by someone who is not an admin
    TOKEN_ACCOUNT_RATE_LIMITED = "token_account_rate_limited"

    # ── phone ───────────────────────────────────────────────────────────────
    PHONE_MISSING = "phone_missing"
    PHONE_CODE_WRONG = "phone_code_wrong"
    PHONE_CODES_LIMIT = "phone_codes_limit"
    TEXTS_NOT_SET_UP = "texts_not_set_up"
    TEXT_NOT_SENT = "text_not_sent"

    # ── machines, readings, alerts, tickets and the rest ────────────────────
    DEVICE_NOT_FOUND = "device_not_found"
    DEVICE_ACCESS_DENIED = "device_access_denied"    # may read the machine, may not change it
    OWNER_NOT_FOUND = "owner_not_found"
    ADMIN_ONLY_FIELD = "admin_only_field"            # a field only an admin may change
    KEY_ROTATION_FORBIDDEN = "key_rotation_forbidden"
    TELEMETRY_NOT_FOUND = "telemetry_not_found"
    ALERT_NOT_FOUND = "alert_not_found"
    RULE_NOT_FOUND = "rule_not_found"
    TICKET_NOT_FOUND = "ticket_not_found"
    TICKET_ACCESS_DENIED = "ticket_access_denied"
    ASSIGNEE_NOT_FOUND = "assignee_not_found"
    ASSIGNEE_REFUSED = "assignee_refused"
    WEBHOOK_NOT_FOUND = "webhook_not_found"
    WEBHOOK_URL_REFUSED = "webhook_url_refused"
    WINDOW_NOT_FOUND = "window_not_found"
    FIRMWARE_NOT_FOUND = "firmware_not_found"
    FIRMWARE_FILE_INVALID = "firmware_file_invalid"
    FIRMWARE_TOO_LARGE = "firmware_too_large"
    NOTHING_TO_SCORE = "nothing_to_score"

    # ── ingest answers (the wire contract of POST /telemetry) ───────────────
    REPLAY_STALE = "replay_stale"                    # a reading older than the device's last accepted one
    REPLAY_PAIR_MISSING = "replay_pair_missing"      # a device that signs its readings with boot and seq sent a reading without them
    COUNTER_OUT_OF_RANGE = "counter_out_of_range"    # a boot or seq no machine could reach
    OBSERVED_AT_TOO_OLD = "observed_at_too_old"      # an observed_at further back than a backlog may reach
    REPLAY_COUNTER_BACK = "replay_counter_back"      # the counter went back without a new boot
    REPLAY_HELD = "replay_held"                      # held after a counter reset until an admin accepts it
    DEVICE_RATE_LIMITED = "device_rate_limited"      # one device posting faster than its allowance
    BATCH_TOO_LARGE = "batch_too_large"              # more readings in a batch than one request may carry

    # ── limits and reads ────────────────────────────────────────────────────
    SIGN_IN_SLOWED = "sign_in_slowed"                # too many failed sign-ins for this account or source
    READ_BUSY = "read_busy"                          # too many heavy reads at once or in a minute
    RETRAIN_COOLDOWN = "retrain_cooldown"
    QUERY_TOO_SLOW = "query_too_slow"                # a read took too long. Ask for less

    # ── contact form and services ───────────────────────────────────────────
    CHALLENGE_FAILED = "challenge_failed"            # the bot check did not pass
    CHALLENGE_UNAVAILABLE = "challenge_unavailable"
    CONTACT_UNAVAILABLE = "contact_unavailable"
    CONTACT_NOT_SENT = "contact_not_sent"

    # ── service accounts, idempotency, stability ────────────────────────────
    IDEMPOTENCY_KEY_REUSED = "idempotency_key_reused"      # the same key with a different body
    IDEMPOTENCY_IN_PROGRESS = "idempotency_in_progress"    # the first request with this key is still running
    ENDPOINT_REMOVED = "endpoint_removed"

    # ── webhooks ────────────────────────────────────────────────────────────
    WEBHOOK_TEMPLATE_INVALID = "webhook_template_invalid"      # a template that uses a placeholder that does not exist
    WEBHOOK_NOT_JSON = "webhook_not_json"                      # the json format was asked for and the body is not JSON
    WEBHOOK_DELIVERY_FAILED = "webhook_delivery_failed"        # the test delivery did not reach the address


CODES = frozenset(value for name, value in vars(Code).items() if name.isupper() and isinstance(value, str))

_STATUS_CODES = {
    400: Code.BAD_REQUEST, 401: Code.UNAUTHENTICATED, 403: Code.FORBIDDEN, 404: Code.NOT_FOUND,
    405: Code.METHOD_NOT_ALLOWED, 409: Code.CONFLICT, 413: Code.PAYLOAD_TOO_LARGE, 422: Code.UNPROCESSABLE,
    429: Code.RATE_LIMITED, 500: Code.INTERNAL_ERROR, 501: Code.NOT_IMPLEMENTED, 502: Code.BAD_GATEWAY,
    503: Code.UNAVAILABLE, 504: Code.GATEWAY_TIMEOUT,
}


def code_for_status(status: int) -> str:
    """The generic code for a status. An HTTPException not yet moved to ApiError gets this one."""
    return _STATUS_CODES.get(status, f"error_{status}")


class ApiError(HTTPException):
    """An error with a stable code. A subclass of HTTPException, so code that catches that keeps working."""

    def __init__(self, status: int, code: str, detail: str, *, headers: dict | None = None, errors: list | None = None):
        super().__init__(status_code=status, detail=detail, headers=headers)
        if code not in CODES:
            # a code must be one of the set, so a client can rely on the list. Loud in development and in tests, where it is
            # found at once and only logged in production, where it must never turn one error into another
            if settings.is_development:
                raise ValueError(f"{code!r} is not in app.errors.Code. Add it there")
            # the stack names the line that raised it. The code itself stays out of the log, since a code is named
            # after what went wrong (a wrong password, say) and a log reader cannot tell it from the thing itself
            logger.error("an error code that is not in app.errors.Code was raised with status %d", status, stack_info=True)
        self.code = code
        self.errors = errors


def request_id_of(request) -> str | None:
    """The id of this request, for an error body. None outside a request that went through the middleware."""
    try:
        return request.state.request_id
    except AttributeError:
        return None


def body(request, status: int, code: str, detail: str, errors: list | None = None) -> dict:
    content: dict = {"code": code, "detail": detail, "request_id": request_id_of(request)}
    if errors is not None:
        content["errors"] = errors
    return content


def _as_sentence(detail) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict) and isinstance(detail.get("detail"), str):
        return detail["detail"]
    return "The request could not be completed"


def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = getattr(exc, "code", None) or code_for_status(exc.status_code)
    detail = _as_sentence(exc.detail)
    if exc.status_code >= 500 and not isinstance(exc, ApiError):
        logger.error("error %s on %s %s (request %s)", exc.status_code, request.method, request.url.path, request_id_of(request))
    headers = dict(getattr(exc, "headers", None) or {})
    if exc.status_code == 429:
        # every 429 says how long to wait and shows the limit headers, whoever raised it. A cooldown or a slowdown has no plain
        # count, so its limit is 0 and what matters is Retry-After
        try:
            retry = max(1, int(headers.get("Retry-After", 60)))
        except (TypeError, ValueError):
            retry = 60
        for name, value in rate_limit_headers(0, retry).items():
            headers.setdefault(name, value)
    return JSONResponse(
        status_code=exc.status_code,
        content=body(request, exc.status_code, code, detail, getattr(exc, "errors", None)),
        headers=headers or None,
    )


def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # the default handler copies the rejected input into the answer. A reading of NaN or infinity cannot be written as JSON, so
    # that turned a refused reading into a 500 and it echoed whatever was sent, passwords included. Only the place, the
    # message and the kind of each fault go back
    errors = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")} for e in exc.errors()]
    first = errors[0]["msg"] if errors else "The request is not valid"
    place = ".".join(str(part) for part in errors[0]["loc"] if part != "body") if errors else ""
    detail = f"The request is not valid: {place + ': ' if place else ''}{first}"
    return JSONResponse(status_code=422, content=body(request, 422, Code.VALIDATION_FAILED, detail, errors))


def retry_after_of(exc: RateLimitExceeded) -> int:
    """Seconds until the limit that was hit lets another call through. At least 1."""
    try:
        return max(1, int(exc.limit.limit.get_expiry()))
    except Exception:  # noqa: BLE001
        return 60


def rate_limit_headers(limit: int, retry_after: int) -> dict:
    return {
        "Retry-After": str(retry_after),
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": "0",
        "X-RateLimit-Reset": str(int(time.time()) + retry_after),
    }


def _rate_limited(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    retry = retry_after_of(exc)
    try:
        amount = int(exc.limit.limit.amount)
    except Exception:  # noqa: BLE001
        amount = 0
    return JSONResponse(
        status_code=429,
        content=body(request, 429, Code.RATE_LIMITED, f"Too many requests. Try again in {retry} seconds"),
        headers=rate_limit_headers(amount, retry),
    )


def _database_error(request: Request, exc: DBAPIError) -> JSONResponse:
    # left alone, the traceback of a failed statement reaches the log with the database's own message, which can quote the row;
    # the kind of error and its SQLSTATE are enough to find the cause
    original = exc.orig
    logger.error(
        "database error %s (SQLSTATE %s) on %s %s (request %s)",
        type(original).__name__, getattr(original, "pgcode", None), request.method, request.url.path, request_id_of(request),
    )
    return JSONResponse(
        status_code=500,
        content=body(request, 500, Code.DATABASE_ERROR, "Something went wrong on our side. Quote the request id if you report it"),
    )


def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unhandled %s on %s %s (request %s)", type(exc).__name__, request.method, request.url.path, request_id_of(request),
    )
    return JSONResponse(
        status_code=500,
        content=body(request, 500, Code.INTERNAL_ERROR, "Something went wrong on our side. Quote the request id if you report it"),
    )


def install(app: FastAPI) -> None:
    """Register every handler. Called once from main.py."""
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(RateLimitExceeded, _rate_limited)
    app.add_exception_handler(DBAPIError, _database_error)
    app.add_exception_handler(Exception, _unhandled)
