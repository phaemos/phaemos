import base64
import hashlib
import hmac
import logging
import io
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlencode

import bcrypt
import httpx
import pyotp
import qrcode
from fastapi import APIRouter, Body, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from jwt import InvalidTokenError
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# passlib (unmaintained since 2020) is incompatible with bcrypt 4.1+ in two ways:
#
# 1. It reads bcrypt.__about__.__version__ to detect the installed version,
#    which bcrypt 4.1+ removed.
# 2. On import it runs its own internal self-test, hashing a deliberately
#    255-byte string to detect an old bcrypt wraparound bug. Old bcrypt
#    silently truncated an overlong secret to 72 bytes; bcrypt 4.1+ correctly
#    raises instead, which crashes passlib's own test, not anything a real
#    caller sent.
#
# restoring the version attribute and bcrypt's old truncate-rather-than-raise
# behaviour fixes both. Real user passwords are separately capped at 72 bytes
# in app/schemas/user.py's password_strength validator, so this only ever
# truncates passlib's internal probe strings, never live input.
if not hasattr(bcrypt, "__about__"):
    class _BcryptAbout:
        __version__ = bcrypt.__version__

    bcrypt.__about__ = _BcryptAbout()

    _real_hashpw = bcrypt.hashpw
    _real_checkpw = bcrypt.checkpw

    def _truncated_hashpw(password: bytes, salt: bytes) -> bytes:
        return _real_hashpw(password[:72], salt)

    def _truncated_checkpw(password: bytes, hashed: bytes) -> bool:
        return _real_checkpw(password[:72], hashed)

    bcrypt.hashpw = _truncated_hashpw
    bcrypt.checkpw = _truncated_checkpw

from app.deps import Page, set_total
from app.errors import ApiError, Code
from app.routes.moved import moved
from app.config import settings
from app.db import get_db
from app.limiter import count_signed_in, limiter
from app.models.api_token import ApiToken
from app.models.user import User
from app.models.email_change import EmailChange
from app.models.invitation import Invitation
from app.models.used_invite import UsedInvite  # noqa: F401  (keeps the retired table in the metadata)
from app.models.user_session import UserSession
from app.schemas.user import (
    UserRegister, UserLogin, UserResponse, TokenResponse, LoginResponse,
    TotpVerify, UserUpdate, ChangePassword, InviteCreate, AcceptInvite, UserSummary, DeleteAccount, OwnerProof,
)
from app.services import audit_service, email_service, signin_guard, token_access
from app.services.keys import derive_key, verification_keys

logger = logging.getLogger(__name__)
router = APIRouter()
# the same routes at their new paths. The ones on `router` under /auth are the old paths, kept for one release
canonical = APIRouter()
class TwoStepSetup(BaseModel):
    qr_code: str
    secret: str


class TwoStepChanged(BaseModel):
    """Two-step was switched on or off. A fresh session comes with it, because every other session has ended."""

    access_token: str
    token_type: str = "bearer"
    message: str
    # repeats `message` for this release. A success body does not use `detail` any more
    detail: str


class AuthorizeUrl(BaseModel):
    authorize_url: str


class ProvidersResponse(BaseModel):
    providers: list[str]


class EndedSessions(BaseModel):
    ended: int


class InviteStatus(BaseModel):
    status: Literal["valid", "expired", "used"]


class SessionSummary(BaseModel):
    id: uuid.UUID
    label: str
    created_at: datetime | None = None
    last_used_at: datetime | None = None
    current: bool


class InviteResult(BaseModel):
    id: uuid.UUID
    message: str
    detail: str
    email_sent: bool
    invite_link: str


pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# use HTTPBearer so FastAPI generates the "Authorise" button in the OpenAPI UI.
_bearer = HTTPBearer()

# guessing is slowed per source and per account by app/services/signin_guard.py (see the table at its top). An account is
# never locked for good by wrong passwords, because that let a stranger who knew an address lock the owner out.

_REFRESH_DAYS = 7
_REFRESH_COOKIE = "refresh_token"
# the refresh cookie is sent only to the two routes that read it: /refresh and /logout. A cookie has one
# path, so it is set twice, once for each route and the browser sends each copy to its own route only. It was
# scoped to the whole /api/v1/auth prefix for a while, which sent it to every auth route, so that wider copy is
# cleared whenever the cookie is set or removed
_REFRESH_PATHS = ("/api/v1/auth/refresh", "/api/v1/auth/logout")
_WIDE_REFRESH_PATH = "/api/v1/auth"

# the challenge issued after a correct password or after OAuth when the
# account has two-factor authentication. It only works at /2fa/verify and
# expires quickly so an unfinished sign-in cannot be resumed later.
_CHALLENGE_MINUTES = 5
_CHALLENGE_COOKIE = "signin_challenge"
_CHALLENGE_PATH = "/api/v1/auth/2fa/verify"

# the OAuth state lives in a short-lived cookie scoped to the auth routes, so
# a callback is only accepted from a sign-in this browser actually started.
_STATE_COOKIE = "oauth_state"
_STATE_PATH = "/api/v1/auth"
_STATE_SECONDS = 600


_BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    # bcrypt is called directly. Only the first 72 bytes count and the schemas refuse a longer password
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode()


# a hash of a password nobody has, made once at import. Sign-in checks against it when an address has no account, so an
# unknown address costs the same time as a known one and the two cannot be told apart by how long the answer takes
_DUMMY_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode()


# stands in for a stored token hash when the token's id is unknown, so the comparison is made either way
_DUMMY_TOKEN_HASH = "0" * 64


def verify_password(plain: str, hashed: str | None) -> bool:
    # accounts created through OAuth have no password, so they can never
    # pass a password check.
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        # a password bcrypt cannot take (a NUL byte or a hash that is not valid) is a wrong password and not an error
        return False


def _encode(data: dict, token_type: str, lifetime: timedelta) -> str:
    # every token carries its type so one kind can never stand in for another;
    # it also carries the user's session version so changing the password or two-factor
    # settings ends every existing session.
    payload = data.copy()
    payload["type"] = token_type
    payload.setdefault("ver", 0)
    payload["exp"] = datetime.now(timezone.utc) + lifetime
    # each kind of token has its own key (see app/services/keys.py), so one signed for a purpose cannot be used for another
    return jwt.encode(payload, derive_key(token_type), algorithm=settings.algorithm)


def _identity(user: User, sid: str | None = None) -> dict:
    claims = {"sub": str(user.id), "role": user.role, "ver": user.token_version or 0}
    if sid:
        # names the server-side session, so signing out ends this token as well
        claims["sid"] = sid
    return claims


def create_access_token(data: dict) -> str:
    return _encode(data, "access", timedelta(minutes=settings.access_token_expire_minutes))


def create_refresh_token(data: dict) -> str:
    return _encode(data, "refresh", timedelta(days=_REFRESH_DAYS))


def create_challenge_token(data: dict) -> str:
    return _encode(data, "challenge", timedelta(minutes=_CHALLENGE_MINUTES))


def decode_token(token: str, token_type: str = "access") -> dict:
    """Decode a JWT and check its type, returning the payload or raising HTTPException."""
    # kept as a standalone helper so the WebSocket route can validate tokens
    # passed as query params without depending on the HTTPBearer scheme.
    payload = None
    # the current key first, then the previous one if a rotation is in progress. Verification only: nothing is signed with it
    for key in verification_keys(token_type):
        try:
            payload = jwt.decode(token, key, algorithms=[settings.algorithm])
            break
        except InvalidTokenError:
            continue
    if payload is None:
        raise ApiError(401, Code.SESSION_ENDED, "Could not validate token")
    if not payload.get("sub") or payload.get("type") != token_type:
        raise ApiError(401, Code.SESSION_ENDED, "Invalid token")
    return payload


def user_for_token(db: Session, payload: dict) -> User:
    """Load the user a decoded token belongs to, refusing tokens from an ended session."""
    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except ValueError:
        raise ApiError(401, Code.SESSION_ENDED, "Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active or user.is_service or (user.token_version or 0) != payload.get("ver", 0):
        raise ApiError(401, Code.SESSION_ENDED, "Session is no longer valid")
    sid = payload.get("sid")
    if payload.get("type") == "access" and not sid and settings.session_id_required:
        # an access token with no session cannot be revoked. Every real one is made with a session, so this only
        # refuses a token minted by someone who holds the signing key
        raise ApiError(401, Code.SESSION_ENDED, "Session is no longer valid")
    if sid:
        # a token that names a session is only good while that session is live
        session = _live_session(db, sid)
        if session is None or session.user_id != user.id:
            raise ApiError(401, Code.SESSION_ENDED, "Session is no longer valid")
    return user


def _live_session(db: Session, sid, lock: bool = False) -> UserSession | None:
    try:
        query = db.query(UserSession).filter(UserSession.id == uuid.UUID(str(sid)))
        # lock=True holds the row until the commit, so two refreshes cannot both rotate the same session
        # populate_existing makes the locked read replace what an earlier unlocked read left in memory
        session = (query.with_for_update().populate_existing() if lock else query).first()
    except ValueError:
        return None
    if session is None or session.revoked_at is not None:
        return None
    if session.expires_at <= datetime.now(timezone.utc):
        return None
    return session


# the class of a route for a method never changes while the app runs
_class_cache: dict[tuple[int, str], token_access.RouteClass] = {}


def _route_class(request: Request) -> token_access.RouteClass:
    # the route with its full path and real dependencies. `scope["route"]` is the original, with no prefix
    route = token_access.effective_route(request.scope)
    if route is None:
        # a caller we cannot place is treated as the strictest class
        return token_access.RouteClass(token_access.SESSION_ONLY)
    key = (id(route), request.method)
    if key not in _class_cache:
        _class_cache[key] = token_access.classify(route, request.method)
    return _class_cache[key]


def _user_for_api_token(request: Request, db: Session, raw: str) -> User:
    """Resolve an access token to its account and enforce what it may do. This is the only place a token is accepted.

    An unknown, malformed, expired or revoked token costs one keyed hash and gets the same 401. The role, the account's
    active state and its session version are read from the database on every call, so lowering a role or deactivating an
    account takes effect on the next request.
    """
    refused = ApiError(401, Code.TOKEN_INVALID, token_access.INVALID, headers={"WWW-Authenticate": "Bearer"})
    parsed = token_access.parse(raw)
    # one hash whatever the input is. A malformed value is hashed too (capped, so a huge header costs no more)
    candidates = token_access.hashes(parsed[1] if parsed else raw[:256])
    row = db.get(ApiToken, parsed[0]) if parsed else None
    stored = row.secret_hash if row is not None else _DUMMY_TOKEN_HASH
    good = token_access.matches(candidates, stored) and row is not None
    now = datetime.now(timezone.utc)
    user = db.get(User, row.user_id) if good else None
    if (
        not good or user is None or row.revoked_at is not None or row.expires_at <= now
        or not user.is_active or (user.token_version or 0) != row.token_version
    ):
        raise refused

    kind = _route_class(request)
    if kind.kind == token_access.SESSION_ONLY:
        raise ApiError(403, Code.SESSION_REQUIRED, token_access.SESSION_NEEDED)
    scope = token_access.effective_scope(row.scope, user.role)
    needed = kind.least_scope or "admin"
    if not token_access.allows(scope, needed):
        raise ApiError(403, Code.SCOPE_TOO_LOW, f"This token's scope ({row.scope}) does not allow this. It needs {needed}")
    # a token cannot be used to get round a per-account limit by making more tokens: every call counts against the account
    if signin_guard.store.incr(f"token-acct:{user.id}", 60) > token_access.ACCOUNT_REQUESTS_PER_MINUTE:
        raise ApiError(429, Code.TOKEN_ACCOUNT_RATE_LIMITED, "Too many requests for this account. Try again in a minute", headers={"Retry-After": "60"})

    if row.last_used_at is None or now - row.last_used_at >= timedelta(minutes=1):
        # at most once a minute. A single conditional update, so two calls together write once
        db.execute(
            update(ApiToken).where(
                ApiToken.id == row.id,
                or_(ApiToken.last_used_at.is_(None), ApiToken.last_used_at < now - timedelta(minutes=1)),
            ).values(last_used_at=now)
        )
        db.commit()
    request.state.api_token = row
    request.state.rate_key = f"token:{row.id}"
    box = token_access.current_token.get()
    if box is not None:
        # the audit service names this token on every row the request writes
        box["id"] = row.id
    return user


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    # factor this into a reusable dependency so any route can require an
    # authenticated user without duplicating the JWT decode + DB lookup logic.
    # it resolves the caller for every route, a session or an access token, so a rule about who may call is made here
    if token_access.looks_like_token(credentials.credentials):
        return _user_for_api_token(request, db, credentials.credentials)
    user = user_for_token(db, decode_token(credentials.credentials, "access"))
    # a verified session is counted by account, so an office behind one address does not share one allowance
    request.state.rate_key = f"user:{user.id}"
    count_signed_in(request.state.rate_key)
    return user


def get_current_sid(credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> str | None:
    """The session the bearer token belongs to or None for a token that names none."""
    if token_access.looks_like_token(credentials.credentials):
        # an access token has no session. A route that needs one refuses the token in get_current_user
        return None
    return decode_token(credentials.credentials, "access").get("sid")


@token_access.session_only_marker
def session_only(user: User = Depends(get_current_user)) -> User:
    """For a route a token may never use. get_current_user refuses the token before this runs. It is the marker."""
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    # keep the role guard as a separate dependency so admin-only routes read
    # cleanly: `Depends(require_admin)` states the intent without an if-block.
    if current_user.role != "admin":
        raise ApiError(403, Code.ADMIN_REQUIRED, "Admin role required")
    return current_user


def _set_cookie(response: Response, key: str, value: str, path: str, max_age: int) -> None:
    response.set_cookie(
        key=key,
        value=value,
        httponly=True,
        secure=not settings.is_development,
        samesite="lax",
        max_age=max_age,
        path=path,
    )


def _clear_cookie(response: Response, key: str, path: str) -> None:
    # expire the cookie by setting max_age=0 rather than deleting it so the
    # browser clears it immediately without needing a separate request.
    _set_cookie(response, key, "", path, 0)


def _agent_label(user_agent: str | None) -> str | None:
    """A coarse description of a browser, such as "Chrome on macOS", from its user agent.

    Only this is kept. The raw user agent and the address are not, because a person does not need either
    to recognise their own session and an address is personal data.
    """
    ua = user_agent or ""
    if not ua:
        return None
    browser = next((name for needle, name in (
        ("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("Safari/", "Safari"),
    ) if needle in ua), "Browser")
    system = next((name for needle, name in (
        ("iPhone", "iOS"), ("iPad", "iOS"), ("Android", "Android"), ("Windows", "Windows"),
        ("Mac OS X", "macOS"), ("Macintosh", "macOS"), ("CrOS", "ChromeOS"), ("Linux", "Linux"),
    ) if needle in ua), None)
    return f"{browser} on {system}" if system else browser


def _start_session(db: Session, user: User, request: Request | None = None) -> UserSession:
    """Record a new signed-in browser. Its refresh token names it and is swapped for a new one on every use."""
    if user.is_service:
        # a service account has no session by any route. This is the last stop if a route forgot to check
        raise ApiError(403, Code.SERVICE_ACCOUNT_REFUSED, "A service account cannot sign in")
    session = UserSession(
        user_id=user.id,
        current_jti=secrets.token_urlsafe(24),
        expires_at=datetime.now(timezone.utc) + timedelta(days=_REFRESH_DAYS),
        label=_agent_label(request.headers.get("user-agent") if request is not None else None),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _refresh_claims(user: User, session: UserSession) -> dict:
    return {**_identity(user, str(session.id)), "jti": session.current_jti}


def _set_refresh_cookie(response: Response, user: User, session: UserSession) -> None:
    token = create_refresh_token(_refresh_claims(user, session))
    # the cookie lasts the lesser of 7 days and what the session has left, so a dead copy never sits in the
    # browser past the end of its session
    left = (session.created_at + timedelta(days=settings.session_max_days) - datetime.now(timezone.utc)).total_seconds()
    max_age = int(max(0, min(_REFRESH_DAYS * 24 * 3600, left)))
    for path in _REFRESH_PATHS:
        _set_cookie(response, _REFRESH_COOKIE, token, path, max_age)
    _clear_cookie(response, _REFRESH_COOKIE, _WIDE_REFRESH_PATH)


def _clear_refresh_cookies(response: Response) -> None:
    for path in (*_REFRESH_PATHS, _WIDE_REFRESH_PATH):
        _clear_cookie(response, _REFRESH_COOKIE, path)


def _session_response(db: Session, user: User, body: dict | None = None, request: Request | None = None) -> JSONResponse:
    """A response carrying a fresh access token and refresh cookie for this user, on a new session."""
    session = _start_session(db, user, request)
    content = {"access_token": create_access_token(_identity(user, str(session.id))), "token_type": "bearer"}
    if body:
        content.update(body)
    response = JSONResponse(content=content)
    _set_refresh_cookie(response, user, session)
    _clear_cookie(response, _CHALLENGE_COOKIE, _CHALLENGE_PATH)
    return response


def revoke_tokens(db: Session, user_id) -> None:
    """Mark every access token of an account revoked. The raised session version already refuses them, so this keeps the list honest."""
    db.query(ApiToken).filter(ApiToken.user_id == user_id, ApiToken.revoked_at.is_(None)).update(
        {"revoked_at": datetime.now(timezone.utc)}, synchronize_session=False
    )


def _end_other_sessions(db: Session, user: User) -> None:
    # bumping the version invalidates every token issued before now. The caller
    # hands the current browser a fresh session straight afterwards.
    user.token_version = (user.token_version or 0) + 1
    # the version already refuses every older token. Marking the rows too keeps the list honest
    db.query(UserSession).filter(UserSession.user_id == user.id, UserSession.revoked_at.is_(None)).update(
        {"revoked_at": datetime.now(timezone.utc)}
    )
    # the same bump ends the account's access tokens. A password change ends a script's token as well, on purpose
    revoke_tokens(db, user.id)
    db.commit()
    db.refresh(user)


def _guard_key(user: User) -> str:
    return signin_guard.account_key(user_id=user.id)


def _check_lockout(user: User | None, trusted_browser: bool = False) -> None:
    """Raise 429 with a wait when this source must slow down for this account. It never locks an account out for good."""
    if user:
        signin_guard.check(_guard_key(user), admin=user.role == "admin", trusted_browser=trusted_browser)


def _clear_failures(db: Session, user: User) -> None:
    """A right password, code or sign-in clears this source's count, so typos spread over a long session never add up."""
    signin_guard.record_success(_guard_key(user))
    if user.failed_login_attempts or user.locked_until:
        user.failed_login_attempts = 0
        user.locked_until = None
        db.commit()


def _record_failure(db: Session, user: User | None) -> None:
    if not user:
        return
    user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
    db.commit()
    key = _guard_key(user)
    failures = signin_guard.record_failure(key)
    # many failures from many places: tell the owner, at most once a day and never once for each attempt
    if signin_guard.over_threshold(failures) and signin_guard.should_notify(key):
        try:
            email_service.send_signin_attempts_notice(user.email)
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not send the sign-in attempts notice (%s)", type(exc).__name__)


# a browser that has signed in to an account before carries a signed cookie for that account. While the account is being
# guessed at from many addresses, such a browser is not slowed down, so the owner gets in. The cookie is not a credential:
# it never signs anyone in, it only skips the account-wide slowdown and the password is still checked
_KNOWN_BROWSER_DAYS = 90
_KNOWN_BROWSER_PATH = "/api/v1/auth"


def _known_browser_cookie(user: User) -> str:
    return f"kb_{user.id.hex[:12]}"


def _set_known_browser(response: Response, user: User) -> None:
    token = _encode({"sub": str(user.id), "ver": user.token_version or 0}, "device", timedelta(days=_KNOWN_BROWSER_DAYS))
    _set_cookie(response, _known_browser_cookie(user), token, _KNOWN_BROWSER_PATH, _KNOWN_BROWSER_DAYS * 24 * 3600)


def _known_browser_ok(request: Request, user: User) -> bool:
    raw = request.cookies.get(_known_browser_cookie(user))
    if not raw:
        return False
    try:
        claims = decode_token(raw, "device")
    except HTTPException:
        return False
    return claims.get("sub") == str(user.id) and claims.get("ver", 0) == (user.token_version or 0)


def _complete_sign_in(db: Session, user: User, request: Request | None = None) -> JSONResponse:
    # reset the failure counter only once every factor has passed, so
    # alternating a correct password with code guesses cannot dodge the lockout.
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    signin_guard.record_success(_guard_key(user))
    response = _session_response(db, user, request=request)
    _set_known_browser(response, user)
    return response


def verify_totp(user: User, code: str) -> bool:
    """Check a one-time code, accepting each time step at most once."""
    # one step either side allows for clock drift. A step at or before the last
    # accepted one is refused, so a code that has been seen cannot be replayed.
    if not user.totp_secret or not code or not code.isdigit():
        return False
    totp = pyotp.TOTP(user.totp_secret)
    now = totp.timecode(datetime.now(timezone.utc))
    for step in (now - 1, now, now + 1):
        if hmac.compare_digest(totp.generate_otp(step), code):
            if user.totp_last_step is not None and step <= user.totp_last_step:
                return False
            user.totp_last_step = step
            return True
    return False


_REGISTRATION_CLOSED = "Registration is closed. Ask an administrator for an invitation."


def _require_registration_open() -> None:
    # a self-made account is a viewer and a viewer reads every machine, so outside
    # development strangers cannot make one unless REGISTRATION_OPEN says so.
    if not settings.registration_is_open:
        raise ApiError(403, Code.REGISTRATION_CLOSED, _REGISTRATION_CLOSED)


@router.post("/register", response_model=UserResponse, status_code=201)
@limiter.limit("10/hour")
def register(request: Request, payload: UserRegister, db: Session = Depends(get_db)):
    _require_registration_open()
    if db.query(User).filter(User.email == payload.email).first():
        raise ApiError(400, Code.EMAIL_IN_USE, "Email already registered")
    user = User(
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        # an address a stranger typed in. It is trusted with a notice only after an hour
        email_since=datetime.now(timezone.utc),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
def login(request: Request, payload: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if user is not None and user.is_service:
        # a service account cannot sign in. It is treated as an address with no account, so the answer, the delay and the
        # counting are the same as for an unknown address and nothing says the address belongs to an integration
        user = None

    # the slowdown is counted for an unknown address exactly as for a known one (by a hash of the address), so neither the
    # status, the text nor the delay says whether the account exists
    key = signin_guard.account_key(user_id=user.id if user else None, email=payload.email)
    signin_guard.check(
        key,
        admin=bool(user and user.role == "admin"),
        trusted_browser=bool(user and _known_browser_ok(request, user)),
    )

    # one bcrypt check whether or not the account exists (and whether or not it has a password), so the time taken does not
    # say. An account with no password or that an admin deactivated, fails the same way as a wrong password
    stored = user.password_hash if user and user.password_hash else None
    matched = verify_password(payload.password, stored or _DUMMY_HASH)
    if not (matched and stored is not None and user is not None and user.is_active):
        if user is not None:
            _record_failure(db, user)
        else:
            signin_guard.record_failure(key)
        raise ApiError(401, Code.INVALID_CREDENTIALS, "Invalid credentials")

    # the password alone is not enough for an account with two-factor
    # authentication: hand back a short-lived challenge that only /2fa/verify
    # accepts instead of a session.
    if user.totp_enabled:
        return {"mfa_required": True, "mfa_token": create_challenge_token(_identity(user)), "token_type": "mfa"}

    return _complete_sign_in(db, user, request)


@router.get("/me", response_model=UserResponse)
def me(
    current_user: User = Depends(get_current_user),
    sid: str | None = Depends(get_current_sid),
    db: Session = Depends(get_db),
):
    # the get_current_user dependency handles decoding and DB lookup. provider_signin_recent is about
    # this session only, so a token from another session never sees another session's proof
    reply = UserResponse.model_validate(current_user)
    reply.provider_signin_recent = _provider_proof_ok(db, sid)
    return reply


def _require_known_origin(request: Request) -> None:
    """Refuse a request from a browser page on another origin to the two routes that act on the refresh cookie.

    SameSite=Lax already stops other sites. A page on a sibling subdomain of the same site is not stopped by it and could
    otherwise force a sign-out or use the cookie. A request with no Origin header (not from a browser page) is allowed.
    """
    origin = request.headers.get("origin")
    if origin and origin not in settings.credentialed_origin_list:
        raise ApiError(403, Code.ORIGIN_NOT_ALLOWED, "Origin not allowed")


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("30/minute")
def refresh(
    request: Request,
    refresh_token: str | None = Cookie(default=None),
    _origin: None = Depends(_require_known_origin),
    db: Session = Depends(get_db),
):
    if not refresh_token:
        raise ApiError(401, Code.REFRESH_MISSING, "Refresh token missing")
    payload = decode_token(refresh_token, "refresh")
    user = user_for_token(db, payload)
    sid, jti = payload.get("sid"), payload.get("jti")
    session = _live_session(db, sid, lock=True) if sid and jti else None
    if session is None or session.user_id != user.id:
        raise ApiError(401, Code.SESSION_ENDED, "Session is no longer valid")
    now = datetime.now(timezone.utc)
    if not hmac.compare_digest(str(jti), session.current_jti):
        # a token that was swapped moments ago is accepted again and gets the same new token back: two tabs
        # refreshing together or a retry after a lost reply, are not theft
        recent = (
            session.previous_jti is not None
            and session.rotated_at is not None
            and hmac.compare_digest(str(jti), session.previous_jti)
            and (now - session.rotated_at).total_seconds() <= settings.refresh_grace_seconds
        )
        if not recent:
            # an older token after the grace: the live one has moved on, so a copy is in use somewhere. End the
            # whole session, which also stops whoever holds the newer token
            session.revoked_at = now
            db.commit()
            raise ApiError(401, Code.SESSION_ENDED, "Session is no longer valid")
        db.commit()  # releases the row lock. Nothing changed
        response = JSONResponse(
            content={"access_token": create_access_token(_identity(user, str(session.id))), "token_type": "bearer"}
        )
        _set_refresh_cookie(response, user, session)
        return response
    # a session also has an absolute end, however often it is refreshed. A copy that is used before each
    # 7 day lapse would otherwise live for ever
    ends = session.created_at + timedelta(days=settings.session_max_days)
    if now >= ends:
        session.revoked_at = now
        db.commit()
        raise ApiError(401, Code.SESSION_ENDED, "Session is no longer valid")
    # swap the token for a new one so each can be used once and remember the old one for the grace
    session.previous_jti = session.current_jti
    session.rotated_at = now
    session.current_jti = secrets.token_urlsafe(24)
    session.last_used_at = now
    session.expires_at = min(now + timedelta(days=_REFRESH_DAYS), ends)
    db.commit()
    db.refresh(session)
    response = JSONResponse(
        content={"access_token": create_access_token(_identity(user, str(session.id))), "token_type": "bearer"}
    )
    _set_refresh_cookie(response, user, session)
    return response


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    _origin: None = Depends(_require_known_origin),
    db: Session = Depends(get_db),
):
    # needs only the cookie, so an expired access token never stops someone signing out. A valid
    # cookie ends its session on the server, which also stops any copy of that refresh token
    if refresh_token:
        try:
            sid = decode_token(refresh_token, "refresh").get("sid")
            session = _live_session(db, sid) if sid else None
            if session is not None:
                session.revoked_at = datetime.now(timezone.utc)
                db.commit()
        except HTTPException:
            pass  # an invalid or expired cookie has nothing to revoke
    _clear_refresh_cookies(response)
    _clear_cookie(response, _CHALLENGE_COOKIE, _CHALLENGE_PATH)


# ── Proof of ownership ────────────────────────────────────────────────────────

_PROVIDER_NAMES = {"google": "Google", "github": "GitHub", "microsoft": "Microsoft"}


PROVIDER_PROOF_MINUTES = 5


def _provider_proof_ok(db: Session, sid: str | None) -> bool:
    """True when this session came back from the sign-in provider in the last 5 minutes."""
    if not sid:
        return False
    session = _live_session(db, sid)
    if session is None or session.provider_signin_at is None:
        return False
    return datetime.now(timezone.utc) - session.provider_signin_at <= timedelta(minutes=PROVIDER_PROOF_MINUTES)


def _require_proof(
    db: Session, user: User, proof: OwnerProof | None, action: str, sid: str | None, second_factor: bool = True
) -> None:
    """Make the caller prove they own the account before an action a stolen token must not be enough for.

    An account with a password sends it and a current two-step code too when two-step is on
    (second_factor=False when the route checks the code itself). A provider account with two-step on
    sends a current code. A provider account with neither must have returned from its provider in the
    last 5 minutes **on this session**, which a thief holding only another session's token cannot do. A
    wrong password or code counts towards the sign-in lock, so these routes cannot be used to guess either.
    """
    proof = proof or OwnerProof()
    if user.password_hash:
        _check_lockout(user)
        if not proof.password:
            raise ApiError(400, Code.PROOF_REQUIRED, f"Enter your current password to {action}")
        if not verify_password(proof.password, user.password_hash):
            _record_failure(db, user)
            raise ApiError(400, Code.PROOF_REQUIRED, f"Enter your current password to {action}")
        if not (second_factor and user.totp_enabled):
            _clear_failures(db, user)
            return
    elif not user.totp_enabled:
        if not _provider_proof_ok(db, sid):
            provider = _PROVIDER_NAMES.get(user.oauth_provider or "", "your provider")
            raise ApiError(400, Code.PROVIDER_PROOF_REQUIRED, f"Sign in with {provider} again within the last 5 minutes to {action}")
        return
    # two-step is on: a current code is needed whether or not there is a password
    _check_lockout(user)
    if not proof.code:
        raise ApiError(400, Code.CODE_REQUIRED, f"Enter a current two-step code to {action}")
    if not verify_totp(user, proof.code):
        _record_failure(db, user)
        raise ApiError(400, Code.CODE_REQUIRED, f"Enter a current two-step code to {action}")
    _clear_failures(db, user)


async def _proof_from_request(request: Request) -> OwnerProof:
    """Read the password and the two-step code a dangerous admin action carries.

    A JSON body holds them as `password` and `code` and a multipart or form body (the firmware upload) as two extra form
    fields of the same names. Anything else or a value that is not text, counts as not sent.
    """
    ctype = request.headers.get("content-type", "").lower()
    data: dict = {}
    try:
        if ctype.startswith("multipart/form-data") or ctype.startswith("application/x-www-form-urlencoded"):
            data = dict(await request.form())
        elif "json" in ctype:
            body = await request.json()
            data = body if isinstance(body, dict) else {}
    except Exception:  # noqa: BLE001
        data = {}
    text = lambda v: v if isinstance(v, str) else None  # noqa: E731
    return OwnerProof(password=text(data.get("password")), code=text(data.get("code")))


def fresh_proof(action: str, admin_only: bool = True):
    """A dependency that asks an admin for their fresh proof before a dangerous action.

    The same rules, messages and status codes as the profile proof routes: 400 for a missing or wrong proof (never 401,
    which means a bad token), a wrong one counts towards the slowdown and a provider-only account proves it with a return
    from its provider in the last 5 minutes on this session. Rate limited to 20 proofs a minute for each account. Pass
    admin_only=False for an action an owner may also take (rotating a machine's key).

        _proof: None = Depends(fresh_proof("add a webhook"))
    """
    @token_access.session_only_marker
    async def dependency(
        request: Request,
        admin: User = Depends(get_current_user),
        sid: str | None = Depends(get_current_sid),
        db: Session = Depends(get_db),
    ) -> None:
        if getattr(request.state, "api_token", None) is not None:
            # also refused in get_current_user. Stated again so this dependency is safe on its own
            raise ApiError(403, Code.SESSION_REQUIRED, token_access.SESSION_NEEDED)
        if admin_only and admin.role != "admin":
            raise ApiError(403, Code.ADMIN_REQUIRED, "Admin role required")
        if not signin_guard.proof_rate_ok(_guard_key(admin)):
            raise ApiError(429, Code.PROOF_RATE_LIMITED, "Too many proofs. Try again in a minute", headers={"Retry-After": "60"})
        proof = await _proof_from_request(request)
        from starlette.concurrency import run_in_threadpool
        await run_in_threadpool(_require_proof, db, admin, proof, action, sid)

    return dependency


# ── Profile management ────────────────────────────────────────────────────────

def _phone_key(value: str | None) -> str:
    """A phone number as it is compared, so only a real change needs proof.

    Empty and missing are the same (no number). Spaces, hyphens and a leading plus are formatting, so a
    number stored as "447700900000" or "+44 7700 900000" equals "+447700900000".
    """
    return re.sub(r"[\s-]", "", value or "").lstrip("+")


def _email_change_allowed(db: Session, user: User) -> None:
    """Refuse a change when the account has already changed its address too often. Counted per hour and per day."""
    now = datetime.now(timezone.utc)
    for window, most in ((timedelta(hours=1), settings.email_changes_per_hour), (timedelta(days=1), settings.email_changes_per_day)):
        count = db.query(EmailChange).filter(EmailChange.user_id == user.id, EmailChange.changed_at > now - window).count()
        if count >= most:
            raise ApiError(429, Code.EMAIL_CHANGES_LIMIT, "You have changed your email too many times. Try again later")


def _old_address_is_trusted(user: User) -> bool:
    """Whether the current sign-in address is one a real owner reads: never unconfirmed or kept for an hour.

    The notice about a change goes only to such an address. A change to an address a stranger chose would
    otherwise make the service mail that stranger's target on demand, from the same quota alert emails use.
    """
    if user.email_since is None:
        return True
    return datetime.now(timezone.utc) - user.email_since >= timedelta(hours=1)


@router.patch("/me", response_model=UserResponse)
@limiter.limit("20/hour")
def update_me(
    request: Request,
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    sid: str | None = Depends(get_current_sid),
    db: Session = Depends(get_db),
):
    changes = payload.model_dump(exclude_none=True)
    proof = OwnerProof(password=changes.pop("current_password", None), code=changes.pop("code", None))
    old_email = current_user.email
    email_changed = "email" in changes and changes["email"] != old_email
    # the phone number is where critical alert texts go, so changing it needs the same proof as the email
    phone_changed = "phone_number" in changes and _phone_key(changes["phone_number"]) != _phone_key(current_user.phone_number)
    if email_changed and current_user.oauth_provider:
        # the address comes from the provider and is how the next sign-in finds the account
        provider = _PROVIDER_NAMES.get(current_user.oauth_provider, "your provider")
        raise ApiError(403, Code.EMAIL_FROM_PROVIDER, f"Your email comes from {provider} and cannot be changed here")
    if email_changed or phone_changed:
        action = "change your email" if email_changed else "change your phone number"
        # a stolen token alone must not be able to move the account to another address or number
        _require_proof(db, current_user, proof, action, sid)
    if email_changed:
        _email_change_allowed(db, current_user)
        if db.query(User).filter(User.email == changes["email"]).first():
            raise ApiError(400, Code.EMAIL_IN_USE, "Email already registered")
    notify = email_changed and _old_address_is_trusted(current_user)
    for field, value in changes.items():
        setattr(current_user, field, value)
    if phone_changed:
        # a new number starts unconfirmed and a code made for the old one is gone
        current_user.phone_confirmed_at = None
        current_user.phone_code_hash = current_user.phone_code_number = current_user.phone_code_expires_at = None
        current_user.phone_code_attempts = 0
    if email_changed:
        current_user.email_since = datetime.now(timezone.utc)
        db.add(EmailChange(user_id=current_user.id))
    db.commit()
    if email_changed:
        # the address a person signs in with has changed, so every other session is ended. This one, which
        # made the change after proving the password, carries on
        others = db.query(UserSession).filter(UserSession.user_id == current_user.id, UserSession.revoked_at.is_(None))
        if sid:
            others = others.filter(UserSession.id != uuid.UUID(str(sid)))
        others.update({"revoked_at": datetime.now(timezone.utc)}, synchronize_session=False)
        db.commit()
        # the old address is told only when a real owner is likely to read it (see _old_address_is_trusted)
        if notify:
            try:
                email_service.send_email_changed_notice(
                    old_email, changes["email"], datetime.now(timezone.utc).strftime("%d %B %Y at %H:%M")
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("could not send the email change notice (%s)", type(exc).__name__)
    db.refresh(current_user)
    return current_user


@router.post("/change-password", status_code=204)
@limiter.limit("10/minute")
def change_password(
    request: Request,
    payload: ChangePassword,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.password_hash:
        # a provider account has no password to change and a guess at one must not count towards its lock
        raise ApiError(400, Code.NO_PASSWORD, "This account has no password. It signs in through its provider")
    # a wrong guess counts towards the same lock as sign-in, so a stolen token cannot be used to guess the password
    _check_lockout(current_user)
    if not verify_password(payload.old_password, current_user.password_hash):
        _record_failure(db, current_user)
        raise ApiError(400, Code.PASSWORD_WRONG, "Current password is incorrect")
    current_user.password_hash = hash_password(payload.new_password)
    _clear_failures(db, current_user)
    # a new password ends every other session. This browser keeps working
    # through the fresh refresh cookie set below.
    _end_other_sessions(db, current_user)
    _set_refresh_cookie(response, current_user, _start_session(db, current_user, request))


def lock_admins(db: Session) -> None:
    """Take a lock on every admin row, always in the same order, so two admins acting at once are made to take turns.

    Whoever gets the lock second sees what the first did, so two admins cannot each remove, demote or deactivate the other
    and leave nobody.
    """
    db.query(User.id).filter(User.role == "admin").order_by(User.id).with_for_update().all()


def other_active_admins(db: Session, user: User) -> int:
    return db.query(User).filter(User.role == "admin", User.is_active.is_(True), User.id != user.id).count()


def _refuse_if_account_cannot_go(db: Session, user: User) -> None:
    """The rules that apply to deleting any account, whoever asks."""
    from app.models.device import Device
    # lock the admin rows while counting, so two admins deleting at once cannot both see the other
    if user.role == "admin":
        lock_admins(db)
    # deleting would leave the machines with no owner, which shares them with every technician
    if db.query(Device).filter(Device.owner_id == user.id).first():
        raise ApiError(409, Code.OWNS_MACHINES, "Hand your machines to another person first")
    if user.role == "admin" and user.is_active and other_active_admins(db, user) == 0:
        raise ApiError(409, Code.LAST_ADMIN, "This is the last admin. Make another person an admin first")


def remove_account(db: Session, user: User) -> None:
    """Remove an account and what is personal in it. Used for a person deleting their own and for an admin removing one.

    Tickets stay with the person taken off (created_by and assigned_to cleared), so the maintenance history stays. Machines
    must already have been handed on (the rule above refuses otherwise). Sessions go with the account by the database. The
    audit trail is kept: its rows hold the account's id as text and no address.
    """
    from app.models.ticket import Ticket
    # updated_at is set to itself so these edits do not restart the retention clock on closed tickets
    db.query(Ticket).filter(Ticket.created_by == user.id).update(
        {"created_by": None, "updated_at": Ticket.updated_at}, synchronize_session=False
    )
    db.query(Ticket).filter(Ticket.assigned_to == user.id).update(
        {"assigned_to": None, "updated_at": Ticket.updated_at}, synchronize_session=False
    )
    db.delete(user)
    db.commit()


@router.delete("/me", status_code=204)
@limiter.limit("5/hour")
def delete_me(
    request: Request,
    proof: DeleteAccount | None = Body(default=None),
    current_user: User = Depends(get_current_user),
    sid: str | None = Depends(get_current_sid),
    db: Session = Depends(get_db),
    response: Response = None,
):
    _require_proof(db, current_user, proof, "delete your account", sid)
    # lock this account's row first, so a machine cannot be handed to it between the check below and the delete
    db.query(User).filter(User.id == current_user.id).with_for_update().first()
    _refuse_if_account_cannot_go(db, current_user)
    remove_account(db, current_user)
    if response:
        _clear_refresh_cookies(response)


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _ticket_export(t, you: User) -> dict:
    # the other party's account id is not this person's data, so only whether it was them is given
    return {
        "id": str(t.id),
        "ticket_number": t.ticket_number,
        "title": t.title,
        "description": t.description,
        "status": t.status,
        "priority": t.priority,
        "device_id": str(t.device_id) if t.device_id else None,
        "alert_id": str(t.alert_id) if t.alert_id else None,
        "created_by_you": t.created_by == you.id,
        "assigned_to_you": t.assigned_to == you.id,
        "created_at": _iso(t.created_at),
        "updated_at": _iso(t.updated_at),
    }


def _assigned_ticket_export(db: Session, t, you: User) -> dict:
    # a ticket can be given to someone who may not read its machine. Its text is not theirs to
    # have, so they get its number and status only
    from app.services.access import can_read_ticket, machine_of_ticket
    if can_read_ticket(you, t, machine_of_ticket(db, t)):
        return _ticket_export(t, you)
    return {
        "id": str(t.id),
        "ticket_number": t.ticket_number,
        "status": t.status,
        "text_withheld": True,
        "created_by_you": t.created_by == you.id,
        "assigned_to_you": True,
    }


@router.get("/me/export", response_class=JSONResponse)
def export_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from sqlalchemy import text
    from fastapi.responses import JSONResponse as _JSONResponse
    from app.models.maintenance import MaintenanceWindow
    from app.models.ticket import Ticket
    from app.models.device import Device
    created = db.query(Ticket).filter(Ticket.created_by == current_user.id).order_by(Ticket.created_at).all()
    assigned = db.query(Ticket).filter(Ticket.assigned_to == current_user.id).order_by(Ticket.created_at).all()
    devices = db.query(Device).filter(Device.owner_id == current_user.id).order_by(Device.created_at).all()
    windows = (
        db.query(MaintenanceWindow).filter(MaintenanceWindow.created_by == current_user.id)
        .order_by(MaintenanceWindow.start_at).all()
    )
    try:
        rows = db.execute(
            text(
                "SELECT action, resource, resource_id, detail, created_at FROM audit_log "
                "WHERE user_id = :uid ORDER BY created_at"
            ),
            {"uid": str(current_user.id)},
        ).all()
    except Exception:  # noqa: BLE001
        # an export that quietly left the log out would look complete and not be. Fail instead
        db.rollback()
        raise ApiError(500, Code.EXPORT_FAILED, "Your log entries could not be read, so nothing was exported. Try again later.")
    bundle = {
        # never the password hash, the two-step secret or the session version
        "profile": {
            "id": str(current_user.id),
            "name": current_user.name,
            "email": current_user.email,
            "phone_number": current_user.phone_number,
            "role": current_user.role,
            "created_at": _iso(current_user.created_at),
            "last_login": _iso(current_user.last_login),
            "sign_in_provider": current_user.oauth_provider,
            "sign_in_provider_id": current_user.oauth_id,
            "has_password": current_user.has_password,
            "two_step_enabled": bool(current_user.totp_enabled),
            "failed_sign_in_attempts": current_user.failed_login_attempts or 0,
            "locked_until": _iso(current_user.locked_until),
            "permissions": current_user.permissions,
        },
        # tickets the person raised and tickets assigned to them, with their descriptions
        # access tokens by name and dates. Never the secret, which is not kept
        "access_tokens": [
            {"id": t.id, "name": t.name, "scope": t.scope, "created_at": _iso(t.created_at),
             "expires_at": _iso(t.expires_at), "last_used_at": _iso(t.last_used_at), "revoked_at": _iso(t.revoked_at)}
            for t in db.query(ApiToken).filter(ApiToken.user_id == current_user.id).order_by(ApiToken.created_at).all()
        ],
        "tickets": [_ticket_export(t, current_user) for t in created],
        "tickets_assigned": [_assigned_ticket_export(db, t, current_user) for t in assigned],
        "devices": [
            {
                "id": str(d.id),
                "name": d.name,
                "type": d.type,
                "location": d.location,
                "status": d.status,
                "firmware_version": d.firmware_version,
                "created_at": _iso(d.created_at),
            }
            for d in devices
        ],
        "maintenance_windows": [
            {
                "id": str(w.id),
                "label": w.label,
                "start_at": _iso(w.start_at),
                "end_at": _iso(w.end_at),
                "device_id": str(w.device_id) if w.device_id else None,
                "suppress_alerts": w.suppress_alerts,
                "created_at": _iso(w.created_at),
            }
            for w in windows
        ],
        "audit_log": [
            {
                "action": r.action,
                "resource": r.resource,
                "resource_id": r.resource_id,
                "detail": r.detail,
                "created_at": _iso(r.created_at),
            }
            for r in rows
        ],
    }
    return _JSONResponse(
        content=bundle,
        headers={"Content-Disposition": "attachment; filename=phaemos-data-export.json"},
    )


# ── 2FA / TOTP ────────────────────────────────────────────────────────────────

@router.post("/2fa/enable", response_model=TwoStepSetup)
def totp_enable(
    proof: OwnerProof | None = Body(default=None),
    current_user: User = Depends(get_current_user),
    sid: str | None = Depends(get_current_sid),
    db: Session = Depends(get_db),
):
    # starting enrolment again would silently switch an active second factor
    # off, so an enabled one has to be disabled with a valid code first.
    if current_user.totp_enabled:
        raise ApiError(409, Code.TWO_STEP_ALREADY_ON, "Two-step sign-in is already on. Turn it off first")
    # a thief with only a token could enrol their own authenticator and lock the owner out
    _require_proof(db, current_user, proof, "turn on two-step sign-in", sid)
    # generate a fresh secret each time so a half-completed enrolment can be
    # restarted without the old unconfirmed secret persisting.
    secret = pyotp.random_base32()
    current_user.totp_secret = secret
    current_user.totp_last_step = None
    db.commit()

    uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=current_user.email,
        issuer_name="PHAEMOS",
    )
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()
    return {"qr_code": qr_b64, "secret": secret}


@router.post("/2fa/confirm", response_model=TwoStepChanged)
@limiter.limit("10/minute")
def totp_confirm(
    request: Request,
    proof: OwnerProof | None = Body(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # the code travels in the JSON body. It is no longer read from the query string, which reaches proxy logs
    code = proof.code if proof else None
    if current_user.totp_enabled:
        raise ApiError(409, Code.TWO_STEP_ALREADY_ON, "Two-step sign-in is already on")
    if not current_user.totp_secret:
        raise ApiError(400, Code.TWO_STEP_NOT_STARTED, "Start two-step setup first")
    # a wrong code counts towards the same lock as sign-in
    _check_lockout(current_user)
    if not code or not verify_totp(current_user, code):
        _record_failure(db, current_user)
        raise ApiError(400, Code.TWO_STEP_CODE_WRONG, "That two-step code is wrong")
    current_user.totp_enabled = True
    _clear_failures(db, current_user)
    # turning on a second factor ends every session that signed in without it.
    _end_other_sessions(db, current_user)
    return _session_response(db, current_user, {"message": "Two-step sign-in is on", "detail": "Two-step sign-in is on"}, request)


@router.post("/2fa/verify", response_model=TokenResponse)
@limiter.limit("10/minute")
def totp_verify(
    request: Request,
    payload: TotpVerify,
    challenge_cookie: str | None = Cookie(default=None, alias=_CHALLENGE_COOKIE),
    db: Session = Depends(get_db),
):
    # the second step of every sign-in. It needs the challenge issued after the
    # first step, from the request body (password sign-in) or from the cookie
    # set by an OAuth callback, so a code on its own never signs anyone in.
    raw = payload.mfa_token or challenge_cookie
    if not raw:
        raise ApiError(401, Code.SIGN_IN_AGAIN, "Sign in again to continue")
    user = user_for_token(db, decode_token(raw, "challenge"))
    if not user.totp_enabled:
        raise ApiError(401, Code.SIGN_IN_AGAIN, "Sign in again to continue")
    _check_lockout(user)
    if not verify_totp(user, payload.code):
        _record_failure(db, user)
        raise ApiError(401, Code.TWO_STEP_CODE_WRONG, "That two-step code is wrong")
    return _complete_sign_in(db, user, request)


@router.post("/2fa/disable", response_model=TwoStepChanged)
@limiter.limit("10/minute")
def totp_disable(
    request: Request,
    proof: OwnerProof | None = Body(default=None),
    current_user: User = Depends(get_current_user),
    sid: str | None = Depends(get_current_sid),
    db: Session = Depends(get_db),
):
    if not current_user.totp_enabled or not current_user.totp_secret:
        raise ApiError(400, Code.TWO_STEP_NOT_ON, "Two-step sign-in is not on")
    _check_lockout(current_user)
    # a password account must also send its password. The code is checked below for every account
    if current_user.password_hash:
        _require_proof(
            db, current_user, OwnerProof(password=proof.password if proof else None),
            "turn off two-step sign-in", sid, second_factor=False,
        )
    code = proof.code if proof else None
    if not code or not verify_totp(current_user, code):
        _record_failure(db, current_user)
        # a wrong proof is a 400, like the others. A 401 means a bad token and the dashboard renews on a 401
        # and tries again, which would count the same wrong code twice
        raise ApiError(400, Code.TWO_STEP_CODE_WRONG, "That two-step code is wrong")
    current_user.totp_enabled = False
    _clear_failures(db, current_user)
    current_user.totp_secret = None
    current_user.totp_last_step = None
    _end_other_sessions(db, current_user)
    return _session_response(db, current_user, {"message": "Two-step sign-in is off", "detail": "Two-step sign-in is off"}, request)


# ── OAuth ─────────────────────────────────────────────────────────────────────

def _oauth_upsert(db: Session, email: str, name: str, provider: str, provider_id: str) -> User:
    """Find or create a user from an OAuth callback. Returns the user record.

    The account is found by the provider and the provider's own identifier first. An address
    is used only for a first link and only to an account that has no password and no provider
    yet, so nobody can reach another person's account by arranging for their address to match.
    Callers only pass an email the provider has verified.
    """
    email = email.strip().lower()
    user = db.query(User).filter(User.oauth_provider == provider, User.oauth_id == provider_id).first()
    if user:
        return user
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        if existing.password_hash or existing.oauth_provider:
            raise ApiError(409, Code.EMAIL_IN_USE, "An account already uses this email. Sign in with your password or the provider you used before.")
        existing.oauth_provider = provider
        existing.oauth_id = provider_id
        db.commit()
        db.refresh(existing)
        return existing
    _require_registration_open()
    user = User(
        name=name,
        email=email,
        password_hash=None,
        oauth_provider=provider,
        oauth_id=provider_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


_LINK_COOKIE = "oauth_link"
_LINKABLE = ("google", "github")


def _provider_authorize(provider: str) -> tuple[str, dict]:
    if provider == "google":
        return "https://accounts.google.com/o/oauth2/v2/auth", {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
        }
    return "https://github.com/login/oauth/authorize", {
        "client_id": settings.github_client_id,
        "redirect_uri": settings.github_redirect_uri,
        "scope": "user:email",
    }


@router.post("/link/{provider}", response_model=AuthorizeUrl)
@limiter.limit("10/minute")
def link_provider_start(
    request: Request,
    provider: str,
    proof: OwnerProof | None = Body(default=None),
    current_user: User = Depends(get_current_user),
    sid: str | None = Depends(get_current_sid),
    db: Session = Depends(get_db),
):
    """Begin linking Google or GitHub to a signed-in account that has a password.

    The proof is checked first (the password and a two-step code when two-step is on), so a stolen token cannot
    attach someone else's provider account. The reply holds the address to send the browser to. It also sets the
    OAuth state cookie and a signed cookie that names this account and this session, which the callback requires.
    Microsoft is not offered, because a Microsoft address is not verified and never links by email.
    """
    if provider not in _LINKABLE:
        raise ApiError(400, Code.PROVIDER_LINK_REFUSED, "That provider cannot be linked to an existing account")
    if not (settings.google_client_id if provider == "google" else settings.github_client_id):
        raise ApiError(501, Code.PROVIDER_NOT_CONFIGURED, f"{_PROVIDER_NAMES[provider]} OAuth not configured")
    if not current_user.password_hash:
        raise ApiError(400, Code.PROVIDER_ALREADY_LINKED, "This account already signs in through its provider")
    if current_user.oauth_provider:
        raise ApiError(409, Code.PROVIDER_ALREADY_LINKED, "A provider is already linked to this account")
    _require_proof(db, current_user, proof, f"link {_PROVIDER_NAMES[provider]}", sid)
    base, params = _provider_authorize(provider)
    state = secrets.token_urlsafe(32)
    response = JSONResponse({"authorize_url": f"{base}?{urlencode({**params, 'state': state})}"})
    _set_cookie(response, _STATE_COOKIE, state, _STATE_PATH, _STATE_SECONDS)
    link = _encode({"sub": str(current_user.id), "ver": current_user.token_version or 0, "sid": sid, "prov": provider},
                   "link", timedelta(seconds=_STATE_SECONDS))
    _set_cookie(response, _LINK_COOKIE, link, _STATE_PATH, _STATE_SECONDS)
    return response


class LinkRefused(HTTPException):
    """A refusal that carries the short code the profile page is told when a link fails."""

    def __init__(self, status_code: int, detail: str, link_code: str):
        super().__init__(status_code=status_code, detail=detail)
        self.link_code = link_code


def _link_error_redirect(code: str) -> RedirectResponse:
    """Send the browser back to the profile page with a fixed code. Never a detail, an address or an identity."""
    frontend = settings.allowed_origins.split(",")[0].strip()
    response = RedirectResponse(url=f"{frontend}/profile?link_error={code}")
    _clear_cookie(response, _LINK_COOKIE, _STATE_PATH)
    _clear_cookie(response, _STATE_COOKIE, _STATE_PATH)
    return response


async def _callback(request: Request, code: str | None, error: str | None, run):
    """Run a provider callback. When it was started to link an account, any refusal becomes a redirect to the profile.

    A sign-in callback behaves as it always has: its errors are the API's own answers.
    """
    linking = bool(request.cookies.get(_LINK_COOKIE))
    if error or not code:
        if linking:
            # the person declined at the provider (access_denied) or the provider sent no code
            return _link_error_redirect("cancelled" if error == "access_denied" else "failed")
        raise ApiError(422, Code.PROVIDER_ERROR, "The provider did not return a sign-in code")
    try:
        return await run()
    except HTTPException as exc:
        if not linking:
            raise
        return _link_error_redirect(getattr(exc, "link_code", "expired" if exc.status_code == 401 else "failed"))
    except Exception:  # noqa: BLE001
        if not linking:
            raise
        return _link_error_redirect("failed")


def _link_provider(db: Session, link_token: str, email: str, provider: str, provider_id: str) -> User:
    """Finish linking: the provider says this address is verified and it must be this account's own address."""
    try:
        claims = decode_token(link_token, "link")
    except HTTPException:
        raise LinkRefused(400, "The link request expired. Start again from your profile", "expired")
    if claims.get("prov") != provider:
        raise LinkRefused(400, "The link request was for a different provider", "failed")
    # the account and the session that asked must still be live and unchanged
    user = user_for_token(db, {"sub": claims.get("sub"), "ver": claims.get("ver", 0), "sid": claims.get("sid")})
    if not user.password_hash or user.oauth_provider:
        raise LinkRefused(409, "A provider is already linked to this account", "failed")
    if (email or "").strip().lower() != user.email.strip().lower():
        raise LinkRefused(
            400, f"The address at {_PROVIDER_NAMES[provider]} is not the address of this account", "address_mismatch"
        )
    taken = db.query(User).filter(User.oauth_provider == provider, User.oauth_id == provider_id).first()
    if taken is not None:
        raise LinkRefused(409, "That provider account is already linked to another account", "identity_in_use")
    user.oauth_provider = provider
    user.oauth_id = provider_id
    db.commit()
    db.refresh(user)
    return user


def _oauth_complete(db: Session, request: Request, email: str, name: str, provider: str, provider_id: str) -> RedirectResponse:
    """The end of a Google or GitHub callback: a link for a signed-in account or an ordinary sign-in."""
    link = request.cookies.get(_LINK_COOKIE)
    if link:
        _link_provider(db, link, email, provider, provider_id)
        frontend = settings.allowed_origins.split(",")[0].strip()
        response = RedirectResponse(url=f"{frontend}/profile?linked={provider}")
        _clear_cookie(response, _LINK_COOKIE, _STATE_PATH)
        _clear_cookie(response, _STATE_COOKIE, _STATE_PATH)
        return response
    user = _oauth_upsert(db, email, name, provider, provider_id)
    return _oauth_finish(db, user, request)


def _oauth_start(authorize_url: str, params: dict) -> RedirectResponse:
    # a random state ties the provider's callback to this browser, so nobody
    # can finish a sign-in they did not start (login CSRF).
    state = secrets.token_urlsafe(32)
    response = RedirectResponse(url=f"{authorize_url}?{urlencode({**params, 'state': state})}")
    _set_cookie(response, _STATE_COOKIE, state, _STATE_PATH, _STATE_SECONDS)
    return response


def _check_state(state: str | None, expected: str | None) -> None:
    if not state or not expected or not hmac.compare_digest(state, expected):
        raise ApiError(400, Code.OAUTH_STATE_INVALID, "Sign-in expired or was not started here. Try again.")


def _oauth_finish(db: Session, user: User, request: Request | None = None) -> RedirectResponse:
    """Send the browser back to the dashboard without putting any token in the URL."""
    if not user.is_active or user.is_service:
        # an admin deactivated this account or it is a service account. It cannot sign in by any route
        raise ApiError(403, Code.ACCOUNT_DISABLED, "This account cannot sign in")
    frontend = settings.allowed_origins.split(",")[0].strip()
    if user.totp_enabled:
        # the provider proves the first factor only. The challenge travels in a
        # cookie that only /2fa/verify reads and the login page asks for the code.
        response = RedirectResponse(url=f"{frontend}/login?step=mfa")
        _set_cookie(response, _CHALLENGE_COOKIE, create_challenge_token(_identity(user)), _CHALLENGE_PATH, _CHALLENGE_MINUTES * 60)
    else:
        user.last_login = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user)
        # the login page swaps the refresh cookie for an access token.
        response = RedirectResponse(url=f"{frontend}/login?step=oauth")
        session = _start_session(db, user, request)
        # the return is recorded on this session and only this session can use it as proof of ownership
        session.provider_signin_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(session)
        _set_refresh_cookie(response, user, session)
    _clear_cookie(response, _STATE_COOKIE, _STATE_PATH)
    return response


@router.get("/providers", response_model=ProvidersResponse)
@limiter.limit("60/minute")
def configured_providers(request: Request):
    """Which sign-in providers are set up, by name only, so the page shows just the ones that work."""
    configured = {
        "google": settings.google_client_id,
        "github": settings.github_client_id,
        "microsoft": settings.microsoft_client_id,
    }
    return {"providers": [name for name, client_id in configured.items() if client_id]}


@router.get("/google", response_class=RedirectResponse, status_code=307)
def google_login():
    # build the authorization URL manually rather than using authlib's
    # session helper so this works in a stateless FastAPI environment without
    # a server-side session store.
    if not settings.google_client_id:
        raise ApiError(501, Code.PROVIDER_NOT_CONFIGURED, "Google OAuth not configured")
    return _oauth_start("https://accounts.google.com/o/oauth2/v2/auth", {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
    })


@router.get("/google/callback", response_class=RedirectResponse, status_code=307)
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    oauth_state: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    return await _callback(request, code, error, lambda: _google_callback(request, code, state, oauth_state, db))


async def _google_callback(
    request: Request,
    code: str,
    state: str | None,
    oauth_state: str | None,
    db: Session,
):
    if not settings.google_client_id:
        raise ApiError(501, Code.PROVIDER_NOT_CONFIGURED, "Google OAuth not configured")
    _check_state(state, oauth_state)
    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    token_data = token_res.json()
    if "error" in token_data:
        raise ApiError(400, Code.PROVIDER_ERROR, token_data.get("error_description", "OAuth error"))

    async with httpx.AsyncClient() as client:
        profile_res = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
        )
    profile = profile_res.json()
    # only a verified address may sign in to an account or link with one.
    if not profile.get("email") or profile.get("email_verified") is not True:
        raise LinkRefused(400, "Your Google account email is not verified", "provider_unverified")
    return _oauth_complete(db, request, profile["email"], profile.get("name", ""), "google", profile["sub"])


@router.get("/github", response_class=RedirectResponse, status_code=307)
def github_login():
    if not settings.github_client_id:
        raise ApiError(501, Code.PROVIDER_NOT_CONFIGURED, "GitHub OAuth not configured")
    return _oauth_start("https://github.com/login/oauth/authorize", {
        "client_id": settings.github_client_id,
        "redirect_uri": settings.github_redirect_uri,
        "scope": "user:email",
    })


@router.get("/github/callback", response_class=RedirectResponse, status_code=307)
async def github_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    oauth_state: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    return await _callback(request, code, error, lambda: _github_callback(request, code, state, oauth_state, db))


async def _github_callback(
    request: Request,
    code: str,
    state: str | None,
    oauth_state: str | None,
    db: Session,
):
    if not settings.github_client_id:
        raise ApiError(501, Code.PROVIDER_NOT_CONFIGURED, "GitHub OAuth not configured")
    _check_state(state, oauth_state)
    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": settings.github_redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
    token_data = token_res.json()
    if "error" in token_data:
        raise ApiError(400, Code.PROVIDER_ERROR, token_data.get("error_description", "OAuth error"))

    access_token = token_data["access_token"]
    async with httpx.AsyncClient() as client:
        profile_res = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
        )
        emails_res = await client.get(
            "https://api.github.com/user/emails",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
        )
    profile = profile_res.json()
    emails = emails_res.json()
    if not isinstance(emails, list):
        emails = []
    # only a verified address may sign in to an account or link with one. The
    # public profile email is not checked by GitHub, so it is never used.
    verified = [e["email"] for e in emails if e.get("verified") and e.get("email")]
    primary = next((e["email"] for e in emails if e.get("primary") and e.get("verified")), None)
    email = primary or (verified[0] if verified else None)
    if not email:
        raise LinkRefused(400, "Could not retrieve a verified email from GitHub", "provider_unverified")
    return _oauth_complete(db, request, email, profile.get("name") or profile.get("login", ""), "github", str(profile["id"]))


def _microsoft_user(db: Session, microsoft_id: str, email: str | None, name: str) -> User:
    """
    Find or create the account for a Microsoft sign-in.

    A work or school tenant can set any email on its users without verifying it, so unlike Google
    and GitHub a Microsoft email never links to an existing account. Only an account this
    Microsoft identity created before is signed in, otherwise a brand-new one is made.
    """
    user = db.query(User).filter(User.oauth_provider == "microsoft", User.oauth_id == microsoft_id).first()
    if user:
        return user
    if not email:
        raise ApiError(400, Code.PROVIDER_ERROR, "Your Microsoft account has no email address to sign in with")
    email = email.strip().lower()
    # decided before the address is looked up, so a closed site never says whether an address has an account
    _require_registration_open()
    if db.query(User).filter(User.email == email).first():
        raise ApiError(409, Code.EMAIL_IN_USE, "An account already uses this email. Sign in with your password or the provider you used before.")
    user = User(name=name, email=email, password_hash=None, oauth_provider="microsoft", oauth_id=microsoft_id)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/microsoft", response_class=RedirectResponse, status_code=307)
def microsoft_login():
    if not settings.microsoft_client_id:
        raise ApiError(501, Code.PROVIDER_NOT_CONFIGURED, "Microsoft OAuth not configured")
    return _oauth_start(f"https://login.microsoftonline.com/{settings.microsoft_tenant}/oauth2/v2.0/authorize", {
        "client_id": settings.microsoft_client_id,
        "redirect_uri": settings.microsoft_redirect_uri,
        "response_type": "code",
        "response_mode": "query",
        "scope": "openid email profile User.Read",
    })


@router.get("/microsoft/callback", response_class=RedirectResponse, status_code=307)
async def microsoft_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    oauth_state: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    return await _callback(request, code, error, lambda: _microsoft_callback(request, code, state, oauth_state, db))


async def _microsoft_callback(
    request: Request,
    code: str,
    state: str | None,
    oauth_state: str | None,
    db: Session,
):
    if not settings.microsoft_client_id:
        raise ApiError(501, Code.PROVIDER_NOT_CONFIGURED, "Microsoft OAuth not configured")
    _check_state(state, oauth_state)
    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            f"https://login.microsoftonline.com/{settings.microsoft_tenant}/oauth2/v2.0/token",
            data={
                "client_id": settings.microsoft_client_id,
                "client_secret": settings.microsoft_client_secret,
                "code": code,
                "redirect_uri": settings.microsoft_redirect_uri,
                "grant_type": "authorization_code",
                "scope": "openid email profile User.Read",
            },
        )
    token_data = token_res.json()
    if "error" in token_data:
        raise ApiError(400, Code.PROVIDER_ERROR, token_data.get("error_description", "OAuth error"))

    async with httpx.AsyncClient() as client:
        profile_res = await client.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
        )
    profile = profile_res.json()
    if not profile.get("id"):
        raise ApiError(400, Code.PROVIDER_ERROR, "Could not read your Microsoft profile")
    email = profile.get("mail") or profile.get("userPrincipalName")
    if request.cookies.get(_LINK_COOKIE):
        raise ApiError(400, Code.PROVIDER_LINK_REFUSED, "Microsoft cannot be linked to an existing account")
    user = _microsoft_user(db, profile["id"], email, profile.get("displayName") or "")
    return _oauth_finish(db, user, request)


# open: Apple sign-in is not built. It needs a paid Apple developer membership, so the route answers 501 for now
@router.get("/apple", response_class=RedirectResponse, status_code=307)
def apple_login():
    raise ApiError(501, Code.PROVIDER_NOT_CONFIGURED, "Apple OAuth coming soon")


# ── Admin ─────────────────────────────────────────────────────────────────────

@moved(router, canonical, "GET", "/users", "/users", response_model=list[UserSummary])
@limiter.limit("60/minute")
def list_users(
    request: Request,
    response: Response,
    _admin: User = Depends(require_admin),
    _session: User = Depends(session_only),
    page: Page = Depends(Page),
    db: Session = Depends(get_db),
):
    # name the admin dependency _admin (underscore prefix) to signal it is
    # only used for its side-effect (role guard), not its return value.
    set_total(response, db.query(User).count())
    users = db.query(User).order_by(User.created_at.desc(), User.id).offset(page.offset).limit(page.limit).all()
    # live sessions for these people, counted in one query
    now = datetime.now(timezone.utc)
    counts = dict(
        db.query(UserSession.user_id, func.count(UserSession.id))
        .filter(UserSession.user_id.in_([u.id for u in users]), UserSession.revoked_at.is_(None), UserSession.expires_at > now)
        .group_by(UserSession.user_id)
        .all()
    ) if users else {}
    out = []
    for u in users:
        row = UserSummary.model_validate(u)
        row.session_count = int(counts.get(u.id, 0))
        out.append(row)
    return out


# ── Sessions ──────────────────────────────────────────────────────────────────

def _own_sessions(db: Session, user: User):
    return (
        db.query(UserSession)
        .filter(UserSession.user_id == user.id, UserSession.revoked_at.is_(None), UserSession.expires_at > datetime.now(timezone.utc))
    )


@router.get("/sessions", response_model=list[SessionSummary])
@limiter.limit("30/minute")
def list_sessions(
    request: Request,
    current_user: User = Depends(get_current_user),
    sid: str | None = Depends(get_current_sid),
    db: Session = Depends(get_db),
):
    """The caller's own live sessions, newest first.

    Each shows when it began, when it was last used, a coarse label such as "Chrome on macOS" and whether it is
    the one asking. No address is shown or kept: a person recognises their own sessions by the browser and the
    times and an address is personal data that adds little. The label comes from the user agent when the session began.
    """
    rows = _own_sessions(db, current_user).order_by(UserSession.created_at.desc(), UserSession.id).all()
    return [
        SessionSummary(
            id=r.id, label=r.label or "Unknown browser", created_at=r.created_at, last_used_at=r.last_used_at,
            current=str(r.id) == str(sid),
        )
        for r in rows
    ]


@router.post("/sessions/end-others", response_model=EndedSessions)
@limiter.limit("10/minute")
def end_other_sessions(
    request: Request,
    current_user: User = Depends(get_current_user),
    sid: str | None = Depends(get_current_sid),
    db: Session = Depends(get_db),
):
    """Sign the account out everywhere else. The session making the call carries on."""
    others = _own_sessions(db, current_user)
    if sid:
        others = others.filter(UserSession.id != uuid.UUID(str(sid)))
    ended = others.update({"revoked_at": datetime.now(timezone.utc)}, synchronize_session=False)
    db.commit()
    return {"ended": ended}


@router.delete("/sessions/{session_id}", status_code=204)
@limiter.limit("20/minute")
def end_session(
    request: Request,
    session_id: uuid.UUID,
    response: Response,
    current_user: User = Depends(get_current_user),
    sid: str | None = Depends(get_current_sid),
    db: Session = Depends(get_db),
):
    # only the caller's own sessions are looked at, so another person's id answers 404 like one that does not exist
    session = _own_sessions(db, current_user).filter(UserSession.id == session_id).first()
    if session is None:
        raise ApiError(404, Code.SESSION_NOT_FOUND, "Session not found")
    session.revoked_at = datetime.now(timezone.utc)
    db.commit()
    if sid and str(session.id) == str(sid):
        # the caller ended their own session, so this browser's cookies are cleared in the same reply
        _clear_refresh_cookies(response)
        _clear_cookie(response, _CHALLENGE_COOKIE, _CHALLENGE_PATH)


# ── Invitation flow ───────────────────────────────────────────────────────────

_INVITE_HOURS = 48


def _hash_invite(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _create_invite(db: Session, email: str, role: str, inviter: User | None = None) -> str:
    """Make an invitation and return its token. Only the hash of the token is stored.

    The token is 256 random bits and not a signed claim, so it cannot be made by anyone who holds a key and an admin can
    list and cancel the invitation. A new invitation to an address cancels any earlier one still open for it.
    """
    now = datetime.now(timezone.utc)
    db.query(Invitation).filter(
        Invitation.email == email, Invitation.used_at.is_(None), Invitation.cancelled_at.is_(None)
    ).update({"cancelled_at": now}, synchronize_session=False)
    token = secrets.token_urlsafe(32)
    db.add(Invitation(
        token_hash=_hash_invite(token), email=email, role=role,
        invited_by=inviter.id if inviter else None, expires_at=now + timedelta(hours=_INVITE_HOURS),
    ))
    db.commit()
    return token


@moved(router, canonical, "POST", "/invite", "/invitations", status_code=201, response_model=InviteResult)
@limiter.limit("10/hour")
def invite_user(
    payload: InviteCreate,
    request: Request,
    admin: User = Depends(require_admin),
    _session: User = Depends(session_only),
    sid: str | None = Depends(get_current_sid),
    db: Session = Depends(get_db),
):
    # inviting an admin hands over full control, so it needs the inviter's fresh proof (password and a code when two-step is on)
    if payload.role == "admin":
        _require_proof(db, admin, OwnerProof(password=payload.password, code=payload.code), "invite an admin", sid)
    if db.query(User).filter(User.email == payload.email).first():
        raise ApiError(400, Code.EMAIL_IN_USE, "Email already registered")
    token = _create_invite(db, payload.email, payload.role, admin)
    created = _find_invitation(db, token)
    audit_service.log_action(db, str(admin.id), "invitation_created", "invitation", str(created.id), f"role={payload.role}")
    # build the accept link from DASHBOARD_URL: the request URL is the API host,
    # which is wrong behind a proxy. The token sits in the fragment, which a browser never
    # sends to a server, so it does not reach web server or hosting logs on first load.
    invite_link = f"{settings.dashboard_url.rstrip('/')}/accept-invite#token={token}"
    sent = email_service.send_invite(payload.email, invite_link, payload.role)
    # the link is returned either way because only an admin reaches this route;
    # when the email did not go out the response says so, so the admin can share the link by hand.
    message = "Invitation sent" if sent else "Invitation created but the email could not be sent. Share the link yourself."
    # `detail` repeats `message` for this release because the dashboard reads it. A success body does not use it any more
    return InviteResult(id=created.id, message=message, detail=message, email_sent=sent, invite_link=invite_link)


class InviteCheck(BaseModel):
    token: str


def _find_invitation(db: Session, token: str, lock: bool = False) -> Invitation | None:
    query = db.query(Invitation).filter(Invitation.token_hash == _hash_invite(token))
    return (query.with_for_update() if lock else query).first()


@router.post("/invite/check", response_model=InviteStatus)
@limiter.limit("30/minute")
def check_invite(request: Request, payload: InviteCheck, db: Session = Depends(get_db)):
    """Whether an invitation can still be used, without using it. The token travels in the body, never the URL.

    Answers only valid, expired or used and nothing about the account. A link that is not a real invitation, one that
    was cancelled and one past its time all answer expired, because none can be used and saying more would say why.
    """
    invitation = _find_invitation(db, payload.token)
    if invitation is None or invitation.cancelled_at is not None or invitation.expires_at <= datetime.now(timezone.utc):
        return {"status": "expired"}
    if invitation.used_at is not None or db.query(User).filter(User.email == invitation.email).first():
        return {"status": "used"}
    return {"status": "valid"}


@router.post("/accept-invite", response_model=UserResponse, status_code=201)
@limiter.limit("10/minute")
def accept_invite(request: Request, payload: AcceptInvite, db: Session = Depends(get_db)):
    # the row is locked, so two clicks at once cannot both use it
    invitation = _find_invitation(db, payload.token, lock=True)
    if invitation is None or invitation.cancelled_at is not None or invitation.expires_at <= datetime.now(timezone.utc):
        raise ApiError(400, Code.INVITATION_INVALID, "Invalid or expired invite token")
    if invitation.used_at is not None:
        raise ApiError(400, Code.INVITATION_USED, "This invitation has already been used")
    if db.query(User).filter(User.email == invitation.email).first():
        raise ApiError(400, Code.ACCOUNT_EXISTS, "Account already exists")
    user = User(
        name=payload.name,
        email=invitation.email,
        password_hash=hash_password(payload.password),
        role=invitation.role,
    )
    invitation.used_at = datetime.now(timezone.utc)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(400, Code.INVITATION_USED, "This invitation has already been used")
    db.refresh(user)
    audit_service.log_action(db, str(user.id), "invitation_accepted", "invitation", str(invitation.id), f"role={user.role}")
    return user
