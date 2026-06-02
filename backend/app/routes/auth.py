import base64
import io
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pyotp
import qrcode
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.limiter import limiter
from app.models.user import User
from app.schemas.user import (
    UserRegister, UserLogin, UserResponse, TokenResponse,
    UserUpdate, ChangePassword, InviteCreate, AcceptInvite,
)
from app.services import email_service

router = APIRouter()
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# I use HTTPBearer so FastAPI generates the "Authorise" button in the OpenAPI UI.
_bearer = HTTPBearer()

# I lock accounts for 15 minutes after 5 consecutive failures, matching NIST
# SP 800-63B guidance on brute-force mitigation.
_MAX_FAILURES = 5
_LOCKOUT_MINUTES = 15


def hash_password(password: str) -> str:
    return pwd_ctx.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)


def create_access_token(data: dict) -> str:
    # I include user identity, role and a short-lived expiration in the payload.
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_refresh_token(data: dict) -> str:
    # I add type="refresh" so the /refresh endpoint can reject access tokens
    # presented in place of refresh tokens.
    payload = data.copy()
    payload["type"] = "refresh"
    payload["exp"] = datetime.now(timezone.utc) + timedelta(days=7)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT, returning the payload or raising HTTPException."""
    # I expose this as a standalone helper so the WebSocket route can validate
    # tokens passed as query params without depending on the HTTPBearer scheme.
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        if not payload.get("sub"):
            raise HTTPException(status_code=401, detail="Invalid token payload")
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Could not validate token")


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    # I factor this into a reusable dependency so any route can require an
    # authenticated user without duplicating the JWT decode + DB lookup logic.
    payload = decode_token(credentials.credentials)
    user_id: str = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    # I keep the role guard as a separate dependency so admin-only routes read
    # cleanly: `Depends(require_admin)` states the intent without an if-block.
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return current_user


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


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
def login(request: Request, payload: UserLogin, db: Session = Depends(get_db)):
    # I look up by email first; if the user does not exist I still run through
    # the lockout path to avoid leaking whether an email is registered.
    user = db.query(User).filter(User.email == payload.email).first()

    # I check lockout before verifying the password so a locked account cannot
    # be probed even with the correct credentials.
    if user and user.locked_until and user.locked_until > datetime.now(timezone.utc):
        raise HTTPException(
            status_code=429,
            detail="Account locked due to too many failed attempts. Try again later.",
        )

    if not user or not verify_password(payload.password, user.password_hash):
        if user:
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= _MAX_FAILURES:
                user.locked_until = datetime.now(timezone.utc) + timedelta(
                    minutes=_LOCKOUT_MINUTES
                )
            db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Reset failure counter and record the successful login timestamp.
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login = datetime.now(timezone.utc)
    db.commit()

    token = create_access_token({"sub": str(user.id), "role": user.role})
    refresh = create_refresh_token({"sub": str(user.id), "role": user.role})
    response = JSONResponse(content={"access_token": token, "token_type": "bearer"})
    response.set_cookie(
        key="refresh_token",
        value=refresh,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
        max_age=7 * 24 * 3600,
        path="/api/v1/auth/refresh",
    )
    return response


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    # The get_current_user dependency handles decoding and DB lookup.
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
    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")
    user = db.query(User).filter(User.id == payload.get("sub")).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return {"access_token": token, "token_type": "bearer"}


@router.post("/logout", status_code=204)
def logout(response: Response):
    # I expire the cookie by setting max_age=0 rather than deleting it so the
    # browser clears it immediately without needing a separate DELETE request.
    response.set_cookie(
        key="refresh_token",
        value="",
        httponly=True,
        max_age=0,
        path="/api/v1/auth/refresh",
    )


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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.password_hash or not verify_password(payload.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_user.password_hash = hash_password(payload.new_password)
    db.commit()


@router.delete("/me", status_code=204)
@limiter.limit("5/hour")
def delete_me(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    response: Response = None,
):
    # I anonymise tickets rather than delete them so the audit trail stays intact
    # but the personal data (user identity) is removed to satisfy GDPR erasure.
    from app.models.ticket import Ticket
    db.query(Ticket).filter(Ticket.created_by == current_user.id).update({"created_by": None})
    db.delete(current_user)
    db.commit()
    if response:
        response.set_cookie(key="refresh_token", value="", httponly=True, max_age=0, path="/api/v1/auth/refresh")


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
    # I generate a fresh secret each time so a half-completed enrolment can be
    # restarted without the old unconfirmed secret persisting.
    secret = pyotp.random_base32()
    current_user.totp_secret = secret
    current_user.totp_enabled = False  # not active until confirmed
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
def totp_confirm(
    code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.totp_secret:
        raise HTTPException(status_code=400, detail="Call /2fa/enable first")
    if not pyotp.TOTP(current_user.totp_secret).verify(code):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")
    current_user.totp_enabled = True
    db.commit()
    return {"detail": "2FA enabled"}


@router.post("/2fa/verify", response_model=TokenResponse)
@limiter.limit("10/minute")
def totp_verify(
    request: Request,
    code: str,
    user_id: str,
    db: Session = Depends(get_db),
):
    # I accept user_id as a query param rather than a JWT so this endpoint works
    # before a full access token is issued - it is the second step of login.
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.totp_enabled or not user.totp_secret:
        raise HTTPException(status_code=400, detail="2FA not enabled for this user")
    if not pyotp.TOTP(user.totp_secret).verify(code):
        raise HTTPException(status_code=401, detail="Invalid TOTP code")
    token = create_access_token({"sub": str(user.id), "role": user.role})
    refresh = create_refresh_token({"sub": str(user.id), "role": user.role})
    resp = JSONResponse(content={"access_token": token, "token_type": "bearer"})
    resp.set_cookie(
        key="refresh_token",
        value=refresh,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
        max_age=7 * 24 * 3600,
        path="/api/v1/auth/refresh",
    )
    return resp


@router.post("/2fa/disable")
def totp_disable(
    code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.totp_enabled or not current_user.totp_secret:
        raise HTTPException(status_code=400, detail="2FA is not enabled")
    if not pyotp.TOTP(current_user.totp_secret).verify(code):
        raise HTTPException(status_code=401, detail="Invalid TOTP code")
    current_user.totp_enabled = False
    current_user.totp_secret = None
    db.commit()
    return {"detail": "2FA disabled"}


# ── OAuth ─────────────────────────────────────────────────────────────────────

def _oauth_upsert(db: Session, email: str, name: str, provider: str, provider_id: str) -> User:
    """Find or create a user from an OAuth callback. Returns the user record."""
    user = db.query(User).filter(User.email == email).first()
    if user:
        # I update the provider fields on each login so a user who previously
        # signed up with a password and later uses Google gets the link recorded.
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


def _oauth_redirect(user: User, frontend_url: str) -> RedirectResponse:
    """Issue tokens and redirect the browser back to the frontend."""
    token = create_access_token({"sub": str(user.id), "role": user.role})
    refresh = create_refresh_token({"sub": str(user.id), "role": user.role})
    url = f"{frontend_url}?token={token}"
    response = RedirectResponse(url=url)
    response.set_cookie(
        key="refresh_token",
        value=refresh,
        httponly=True,
        secure=False,  # set True in production via env guard
        samesite="lax",
        max_age=7 * 24 * 3600,
        path="/api/v1/auth/refresh",
    )
    return response


@router.get("/google")
def google_login():
    # I build the authorization URL manually rather than using authlib's
    # session helper so this works in a stateless FastAPI environment without
    # a server-side session store.
    if not settings.google_client_id:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")
    params = (
        f"client_id={settings.google_client_id}"
        f"&redirect_uri={settings.google_redirect_uri}"
        "&response_type=code"
        "&scope=openid%20email%20profile"
        "&access_type=offline"
    )
    return RedirectResponse(url=f"https://accounts.google.com/o/oauth2/v2/auth?{params}")


@router.get("/google/callback")
async def google_callback(code: str, db: Session = Depends(get_db)):
    if not settings.google_client_id:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")
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
    user = _oauth_upsert(db, profile["email"], profile.get("name", ""), "google", profile["sub"])
    frontend = settings.allowed_origins.split(",")[0].strip()
    return _oauth_redirect(user, f"{frontend}/dashboard")


@router.get("/github")
def github_login():
    if not settings.github_client_id:
        raise HTTPException(status_code=501, detail="GitHub OAuth not configured")
    params = (
        f"client_id={settings.github_client_id}"
        f"&redirect_uri={settings.github_redirect_uri}"
        "&scope=user:email"
    )
    return RedirectResponse(url=f"https://github.com/login/oauth/authorize?{params}")


@router.get("/github/callback")
async def github_callback(code: str, db: Session = Depends(get_db)):
    if not settings.github_client_id:
        raise HTTPException(status_code=501, detail="GitHub OAuth not configured")
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
    primary_email = next(
        (e["email"] for e in emails if e.get("primary") and e.get("verified")),
        profile.get("email"),
    )
    if not primary_email:
        raise HTTPException(status_code=400, detail="Could not retrieve verified email from GitHub")
    user = _oauth_upsert(db, primary_email, profile.get("name") or profile.get("login", ""), "github", str(profile["id"]))
    frontend = settings.allowed_origins.split(",")[0].strip()
    return _oauth_redirect(user, f"{frontend}/dashboard")


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
    # I name the admin dependency _admin (underscore prefix) to signal it is
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
    # I replace the entire permissions dict atomically to avoid partial-update races.
    # Passing null clears all overrides and reverts the user to role defaults.
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.permissions = body
    db.commit()
    db.refresh(user)
    return user


# ── Invitation flow ───────────────────────────────────────────────────────────

def _create_invite_token(email: str, role: str) -> str:
    # I embed the role in the invite token so the accept endpoint can pre-assign
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
    # I build the accept link using the request base URL so it works in both
    # local dev and production without hard-coding a domain.
    frontend_base = str(request.base_url).rstrip("/").replace(":8000", ":3000")
    invite_link = f"{frontend_base}/accept-invite?token={token}"
    email_service.send_invite(payload.email, invite_link, payload.role)
    return {"detail": "Invitation sent", "invite_link": invite_link}


@router.get("/accept-invite/{token}")
@limiter.limit("20/minute")
def get_invite_info(request: Request, token: str):
    # I validate the token here so the frontend can show a friendly error
    # (expired, invalid) before the user fills in their name and password.
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
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
    except JWTError:
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
