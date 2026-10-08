import base64
import hmac
import io
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import bcrypt
import httpx
import pyotp
import qrcode
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from jwt import InvalidTokenError
from passlib.context import CryptContext
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

from app.config import settings
from app.db import get_db
from app.limiter import limiter
from app.models.user import User
from app.schemas.user import (
    UserRegister, UserLogin, UserResponse, TokenResponse, LoginResponse,
    TotpVerify, UserUpdate, ChangePassword, InviteCreate, AcceptInvite,
)
from app.services import email_service

router = APIRouter()
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# use HTTPBearer so FastAPI generates the "Authorise" button in the OpenAPI UI.
_bearer = HTTPBearer()

# lock accounts for 15 minutes after 5 consecutive failures, matching NIST
# SP 800-63B guidance on brute-force mitigation. Wrong second-factor codes
# count towards the same limit as wrong passwords.
_MAX_FAILURES = 5
_LOCKOUT_MINUTES = 15

_REFRESH_DAYS = 7
_REFRESH_COOKIE = "refresh_token"
_REFRESH_PATH = "/api/v1/auth/refresh"

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


def hash_password(password: str) -> str:
    return pwd_ctx.hash(password)


def verify_password(plain: str, hashed: str | None) -> bool:
    # accounts created through OAuth have no password, so they can never
    # pass a password check.
    if not hashed:
        return False
    return pwd_ctx.verify(plain, hashed)


def _encode(data: dict, token_type: str, lifetime: timedelta) -> str:
    # every token carries its type so one kind can never stand in for another,
    # and the user's session version so changing the password or two-factor
    # settings ends every existing session.
    payload = data.copy()
    payload["type"] = token_type
    payload.setdefault("ver", 0)
    payload["exp"] = datetime.now(timezone.utc) + lifetime
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def _identity(user: User) -> dict:
    return {"sub": str(user.id), "role": user.role, "ver": user.token_version or 0}


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
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Could not validate token")
    if not payload.get("sub") or payload.get("type") != token_type:
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload


def user_for_token(db: Session, payload: dict) -> User:
    """Load the user a decoded token belongs to, refusing tokens from an ended session."""
    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user or (user.token_version or 0) != payload.get("ver", 0):
        raise HTTPException(status_code=401, detail="Session is no longer valid")
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    # factor this into a reusable dependency so any route can require an
    # authenticated user without duplicating the JWT decode + DB lookup logic.
    return user_for_token(db, decode_token(credentials.credentials, "access"))


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    # keep the role guard as a separate dependency so admin-only routes read
    # cleanly: `Depends(require_admin)` states the intent without an if-block.
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return current_user


def _set_cookie(response: Response, key: str, value: str, path: str, max_age: int) -> None:
    response.set_cookie(
        key=key,
        value=value,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
        max_age=max_age,
        path=path,
    )


def _clear_cookie(response: Response, key: str, path: str) -> None:
    # expire the cookie by setting max_age=0 rather than deleting it so the
    # browser clears it immediately without needing a separate request.
    _set_cookie(response, key, "", path, 0)


def _set_refresh_cookie(response: Response, user: User) -> None:
    _set_cookie(response, _REFRESH_COOKIE, create_refresh_token(_identity(user)),
                _REFRESH_PATH, _REFRESH_DAYS * 24 * 3600)


def _session_response(user: User, body: dict | None = None) -> JSONResponse:
    """A response carrying a fresh access token and refresh cookie for this user."""
    content = {"access_token": create_access_token(_identity(user)), "token_type": "bearer"}
    if body:
        content.update(body)
    response = JSONResponse(content=content)
    _set_refresh_cookie(response, user)
    _clear_cookie(response, _CHALLENGE_COOKIE, _CHALLENGE_PATH)
    return response


def _end_other_sessions(db: Session, user: User) -> None:
    # bumping the version invalidates every token issued before now. The caller
    # hands the current browser a fresh session straight afterwards.
    user.token_version = (user.token_version or 0) + 1
    db.commit()
    db.refresh(user)


def _check_lockout(user: User | None) -> None:
    if user and user.locked_until and user.locked_until > datetime.now(timezone.utc):
        raise HTTPException(
            status_code=429,
            detail="Account locked due to too many failed attempts. Try again later.",
        )


def _record_failure(db: Session, user: User | None) -> None:
    if not user:
        return
    user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
    if user.failed_login_attempts >= _MAX_FAILURES:
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=_LOCKOUT_MINUTES)
    db.commit()


def _complete_sign_in(db: Session, user: User) -> JSONResponse:
    # reset the failure counter only once every factor has passed, so
    # alternating a correct password with code guesses cannot dodge the lockout.
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return _session_response(user)


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


@router.post("/register", response_model=UserResponse, status_code=201)
@limiter.limit("10/hour")
def register(request: Request, payload: UserRegister, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
def login(request: Request, payload: UserLogin, db: Session = Depends(get_db)):
    # look up by email first; if the user does not exist, still run through
    # the lockout path to avoid leaking whether an email is registered.
    user = db.query(User).filter(User.email == payload.email).first()

    # check lockout before verifying the password so a locked account cannot
    # be probed even with the correct credentials.
    _check_lockout(user)

    if not user or not verify_password(payload.password, user.password_hash):
        _record_failure(db, user)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # the password alone is not enough for an account with two-factor
    # authentication: hand back a short-lived challenge that only /2fa/verify
    # accepts instead of a session.
    if user.totp_enabled:
        return {"mfa_required": True, "mfa_token": create_challenge_token(_identity(user)), "token_type": "mfa"}

    return _complete_sign_in(db, user)


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    # the get_current_user dependency handles decoding and DB lookup.
    return current_user


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("30/minute")
def refresh(
    request: Request,
    refresh_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token missing")
    user = user_for_token(db, decode_token(refresh_token, "refresh"))
    return {"access_token": create_access_token(_identity(user)), "token_type": "bearer"}


@router.post("/logout", status_code=204)
def logout(response: Response):
    _clear_cookie(response, _REFRESH_COOKIE, _REFRESH_PATH)
    _clear_cookie(response, _CHALLENGE_COOKIE, _CHALLENGE_PATH)


# ── Profile management ────────────────────────────────────────────────────────

@router.patch("/me", response_model=UserResponse)
def update_me(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.email and payload.email != current_user.email:
        if db.query(User).filter(User.email == payload.email).first():
            raise HTTPException(status_code=400, detail="Email already registered")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(current_user, field, value)
    db.commit()
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
    if not verify_password(payload.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_user.password_hash = hash_password(payload.new_password)
    # a new password ends every other session. This browser keeps working
    # through the fresh refresh cookie set below.
    _end_other_sessions(db, current_user)
    _set_refresh_cookie(response, current_user)


@router.delete("/me", status_code=204)
@limiter.limit("5/hour")
def delete_me(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    response: Response = None,
):
    # anonymise tickets rather than delete them so the audit trail stays intact
    # but the personal data (user identity) is removed to satisfy GDPR erasure.
    from app.models.ticket import Ticket
    db.query(Ticket).filter(Ticket.created_by == current_user.id).update({"created_by": None})
    db.delete(current_user)
    db.commit()
    if response:
        _clear_cookie(response, _REFRESH_COOKIE, _REFRESH_PATH)


@router.get("/me/export")
def export_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from fastapi.responses import JSONResponse as _JSONResponse
    from app.models.ticket import Ticket
    from app.models.device import Device
    tickets = db.query(Ticket).filter(Ticket.created_by == current_user.id).all()
    devices = db.query(Device).filter(Device.owner_id == current_user.id).all()
    bundle = {
        "profile": {
            "id": str(current_user.id),
            "name": current_user.name,
            "email": current_user.email,
            "phone_number": current_user.phone_number,
            "role": current_user.role,
            "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
        },
        "tickets": [
            {"id": str(t.id), "title": t.title, "status": t.status, "created_at": t.created_at.isoformat() if t.created_at else None}
            for t in tickets
        ],
        "devices": [
            {"id": str(d.id), "name": d.name, "type": d.type}
            for d in devices
        ],
    }
    return _JSONResponse(
        content=bundle,
        headers={"Content-Disposition": "attachment; filename=phaemos-data-export.json"},
    )


# ── 2FA / TOTP ────────────────────────────────────────────────────────────────

@router.post("/2fa/enable")
def totp_enable(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # starting enrolment again would silently switch an active second factor
    # off, so an enabled one has to be disabled with a valid code first.
    if current_user.totp_enabled:
        raise HTTPException(status_code=409, detail="2FA is already enabled. Disable it first.")
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


@router.post("/2fa/confirm")
@limiter.limit("10/minute")
def totp_confirm(
    request: Request,
    code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.totp_enabled:
        raise HTTPException(status_code=409, detail="2FA is already enabled")
    if not current_user.totp_secret:
        raise HTTPException(status_code=400, detail="Call /2fa/enable first")
    if not verify_totp(current_user, code):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")
    current_user.totp_enabled = True
    # turning on a second factor ends every session that signed in without it.
    _end_other_sessions(db, current_user)
    return _session_response(current_user, {"detail": "2FA enabled"})


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
        raise HTTPException(status_code=401, detail="Sign in again to continue")
    user = user_for_token(db, decode_token(raw, "challenge"))
    if not user.totp_enabled:
        raise HTTPException(status_code=401, detail="Sign in again to continue")
    _check_lockout(user)
    if not verify_totp(user, payload.code):
        _record_failure(db, user)
        raise HTTPException(status_code=401, detail="Invalid TOTP code")
    return _complete_sign_in(db, user)


@router.post("/2fa/disable")
@limiter.limit("10/minute")
def totp_disable(
    request: Request,
    code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.totp_enabled or not current_user.totp_secret:
        raise HTTPException(status_code=400, detail="2FA is not enabled")
    if not verify_totp(current_user, code):
        raise HTTPException(status_code=401, detail="Invalid TOTP code")
    current_user.totp_enabled = False
    current_user.totp_secret = None
    current_user.totp_last_step = None
    _end_other_sessions(db, current_user)
    return _session_response(current_user, {"detail": "2FA disabled"})


# ── OAuth ─────────────────────────────────────────────────────────────────────

def _oauth_upsert(db: Session, email: str, name: str, provider: str, provider_id: str) -> User:
    """Find or create a user from an OAuth callback. Returns the user record."""
    # callers only pass an email the provider has verified, which is what makes
    # linking it to an existing account by email safe.
    user = db.query(User).filter(User.email == email).first()
    if user:
        user.oauth_provider = provider
        user.oauth_id = provider_id
    else:
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


def _oauth_start(authorize_url: str, params: dict) -> RedirectResponse:
    # a random state ties the provider's callback to this browser, so nobody
    # can finish a sign-in they did not start (login CSRF).
    state = secrets.token_urlsafe(32)
    response = RedirectResponse(url=f"{authorize_url}?{urlencode({**params, 'state': state})}")
    _set_cookie(response, _STATE_COOKIE, state, _STATE_PATH, _STATE_SECONDS)
    return response


def _check_state(state: str | None, expected: str | None) -> None:
    if not state or not expected or not hmac.compare_digest(state, expected):
        raise HTTPException(status_code=400, detail="Sign-in expired or was not started here. Try again.")


def _oauth_finish(db: Session, user: User) -> RedirectResponse:
    """Send the browser back to the dashboard without putting any token in the URL."""
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
        _set_refresh_cookie(response, user)
    _clear_cookie(response, _STATE_COOKIE, _STATE_PATH)
    return response


@router.get("/google")
def google_login():
    # build the authorization URL manually rather than using authlib's
    # session helper so this works in a stateless FastAPI environment without
    # a server-side session store.
    if not settings.google_client_id:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")
    return _oauth_start("https://accounts.google.com/o/oauth2/v2/auth", {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
    })


@router.get("/google/callback")
async def google_callback(
    code: str,
    state: str | None = None,
    oauth_state: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    if not settings.google_client_id:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")
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
        raise HTTPException(status_code=400, detail=token_data.get("error_description", "OAuth error"))

    async with httpx.AsyncClient() as client:
        profile_res = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
        )
    profile = profile_res.json()
    # only a verified address may sign in to an account or link with one.
    if not profile.get("email") or profile.get("email_verified") is not True:
        raise HTTPException(status_code=400, detail="Your Google account email is not verified")
    user = _oauth_upsert(db, profile["email"], profile.get("name", ""), "google", profile["sub"])
    return _oauth_finish(db, user)


@router.get("/github")
def github_login():
    if not settings.github_client_id:
        raise HTTPException(status_code=501, detail="GitHub OAuth not configured")
    return _oauth_start("https://github.com/login/oauth/authorize", {
        "client_id": settings.github_client_id,
        "redirect_uri": settings.github_redirect_uri,
        "scope": "user:email",
    })


@router.get("/github/callback")
async def github_callback(
    code: str,
    state: str | None = None,
    oauth_state: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    if not settings.github_client_id:
        raise HTTPException(status_code=501, detail="GitHub OAuth not configured")
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
        raise HTTPException(status_code=400, detail=token_data.get("error_description", "OAuth error"))

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
        raise HTTPException(status_code=400, detail="Could not retrieve a verified email from GitHub")
    user = _oauth_upsert(db, email, profile.get("name") or profile.get("login", ""), "github", str(profile["id"]))
    return _oauth_finish(db, user)


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
        raise HTTPException(status_code=400, detail="Your Microsoft account has no email address to sign in with")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(
            status_code=409,
            detail="An account already uses this email. Sign in with your password or the provider you used before.",
        )
    user = User(name=name, email=email, password_hash=None, oauth_provider="microsoft", oauth_id=microsoft_id)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/microsoft")
def microsoft_login():
    if not settings.microsoft_client_id:
        raise HTTPException(status_code=501, detail="Microsoft OAuth not configured")
    return _oauth_start(f"https://login.microsoftonline.com/{settings.microsoft_tenant}/oauth2/v2.0/authorize", {
        "client_id": settings.microsoft_client_id,
        "redirect_uri": settings.microsoft_redirect_uri,
        "response_type": "code",
        "response_mode": "query",
        "scope": "openid email profile User.Read",
    })


@router.get("/microsoft/callback")
async def microsoft_callback(
    code: str,
    state: str | None = None,
    oauth_state: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    if not settings.microsoft_client_id:
        raise HTTPException(status_code=501, detail="Microsoft OAuth not configured")
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
        raise HTTPException(status_code=400, detail=token_data.get("error_description", "OAuth error"))

    async with httpx.AsyncClient() as client:
        profile_res = await client.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
        )
    profile = profile_res.json()
    if not profile.get("id"):
        raise HTTPException(status_code=400, detail="Could not read your Microsoft profile")
    email = profile.get("mail") or profile.get("userPrincipalName")
    user = _microsoft_user(db, profile["id"], email, profile.get("displayName") or "")
    return _oauth_finish(db, user)


# TODO Step 20b: implement Apple OAuth when Apple Developer Programme enrolled
@router.get("/apple")
def apple_login():
    raise HTTPException(status_code=501, detail="Apple OAuth coming soon")


# ── Admin ─────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserResponse])
def list_users(
    skip: int = 0,
    limit: int = 50,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    # name the admin dependency _admin (underscore prefix) to signal it is
    # only used for its side-effect (role guard), not its return value.
    return (
        db.query(User)
        .order_by(User.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.patch("/users/{user_id}/permissions", response_model=UserResponse)
def set_user_permissions(
    user_id: uuid.UUID,
    body: dict[str, Any] | None,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    # replace the entire permissions dict atomically to avoid partial-update races.
    # passing null clears all overrides and reverts the user to role defaults.
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.permissions = body
    db.commit()
    db.refresh(user)
    return user


# ── Invitation flow ───────────────────────────────────────────────────────────

def _create_invite_token(email: str, role: str) -> str:
    # embed the role in the invite token so the accept endpoint can pre-assign
    # it without a second DB lookup or a separate parameter in the accept form.
    payload = {
        "sub":  email,
        "role": role,
        "type": "invite",
        "exp":  datetime.now(timezone.utc) + timedelta(hours=48),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


@router.post("/invite", status_code=201)
@limiter.limit("10/hour")
def invite_user(
    payload: InviteCreate,
    request: Request,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    token = _create_invite_token(payload.email, payload.role)
    # build the accept link using the request base URL so it works in both
    # local dev and production without hard-coding a domain.
    frontend_base = str(request.base_url).rstrip("/").replace(":8000", ":3000")
    invite_link = f"{frontend_base}/accept-invite?token={token}"
    email_service.send_invite(payload.email, invite_link, payload.role)
    return {"detail": "Invitation sent", "invite_link": invite_link}


@router.get("/accept-invite/{token}")
@limiter.limit("20/minute")
def get_invite_info(request: Request, token: str):
    # validate the token here so the frontend can show a friendly error
    # (expired, invalid) before the user fills in their name and password.
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except InvalidTokenError:
        raise HTTPException(status_code=400, detail="Invalid or expired invite token")
    if payload.get("type") != "invite":
        raise HTTPException(status_code=400, detail="Invalid token type")
    return {"email": payload.get("sub"), "role": payload.get("role")}


@router.post("/accept-invite", response_model=UserResponse, status_code=201)
@limiter.limit("10/minute")
def accept_invite(request: Request, payload: AcceptInvite, db: Session = Depends(get_db)):
    try:
        token_data = jwt.decode(
            payload.token, settings.secret_key, algorithms=[settings.algorithm]
        )
    except InvalidTokenError:
        raise HTTPException(status_code=400, detail="Invalid or expired invite token")
    if token_data.get("type") != "invite":
        raise HTTPException(status_code=400, detail="Invalid token type")
    email = token_data.get("sub")
    role  = token_data.get("role", "viewer")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Account already exists")
    user = User(
        name=payload.name,
        email=email,
        password_hash=hash_password(payload.password),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
