"""
Admin control over accounts and invitations and the password reset an admin's link leads to.

After a stolen account or a leaver the response was a database command on the server. These routes are that response.
Rules every one follows:

* the admin's fresh proof (the password and a two-step code when it is on or for a provider-only account a return from the
  provider in the last 5 minutes on this session) is asked for before anything changes, with the same messages and status
  codes as the profile proof routes: 400 for a missing or wrong proof
* every change writes an audit row naming the admin and the account (an id, never an address)
* an admin cannot deactivate, demote or remove themselves and the last active admin cannot be demoted, deactivated or
  removed. The admin rows are locked in a fixed order first, so two admins acting at once take turns and cannot each
  remove the other
* a reset link is sent to the account's own address and is never shown to the admin
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.errors import ApiError, Code
from app.routes.moved import moved
from app.config import settings
from app.db import get_db
from app.deps import Page, set_total
from app.limiter import limiter, named
from app.models.invitation import Invitation
from app.models.user import User
from app.models.user_session import UserSession
from app.routes.auth import (
    session_only, _clear_failures, _encode, _refuse_if_account_cannot_go, decode_token, fresh_proof, hash_password,
    lock_admins, other_active_admins, remove_account, require_admin, revoke_tokens,
)
from app.schemas.user import InvitationSummary, ServiceAccountCreate, UserSummary, check_password
from app.services import audit_service, email_service, signin_guard
from pydantic import field_validator

class ResetLinkSent(BaseModel):
    message: str
    detail: str
    email_sent: bool


router = APIRouter()
# the same routes at their new paths (/users, /invitations). The ones on `router` are the old /auth paths, kept for one release
canonical = APIRouter()

_RESET_HOURS = 2


class RoleChange(BaseModel):
    role: Literal["admin", "technician", "viewer"]


class ResetPassword(BaseModel):
    token: str
    password: str

    @field_validator("password")
    @classmethod
    def strength(cls, v: str) -> str:
        return check_password(v)


def _target(db: Session, user_id: uuid.UUID) -> User:
    user = db.query(User).filter(User.id == user_id).with_for_update().first()
    if user is None:
        raise ApiError(404, Code.USER_NOT_FOUND, "User not found")
    return user


def _not_self(admin: User, target: User, what: str) -> None:
    if admin.id == target.id:
        raise ApiError(403, Code.SELF_ACTION_REFUSED, f"You cannot {what} your own account")


def _last_admin_guard(db: Session, target: User, what: str) -> None:
    """Refuse when the action would leave no active admin. The admin rows are locked first."""
    if target.role == "admin" and target.is_active and other_active_admins(db, target) == 0:
        raise ApiError(409, Code.LAST_ADMIN, f"This is the last active admin. It cannot be {what}")


def _end_sessions(db: Session, target: User) -> None:
    # the version refuses every token already issued and the rows are marked so the list is honest
    target.token_version = (target.token_version or 0) + 1
    db.query(UserSession).filter(UserSession.user_id == target.id, UserSession.revoked_at.is_(None)).update(
        {"revoked_at": datetime.now(timezone.utc)}, synchronize_session=False
    )
    # the account's access tokens go with its sessions
    revoke_tokens(db, target.id)


@moved(router, canonical, "POST", "/users/{user_id}/deactivate", "/users/{user_id}/deactivate", status_code=204)
@limiter.limit("20/hour")
def deactivate_user(
    request: Request, user_id: uuid.UUID,
    admin: User = Depends(require_admin), _proof: None = Depends(fresh_proof("deactivate this account")),
    db: Session = Depends(get_db),
):
    lock_admins(db)
    target = _target(db, user_id)
    _not_self(admin, target, "deactivate")
    _last_admin_guard(db, target, "deactivated")
    if target.is_active:
        target.is_active = False
        target.deactivated_at = datetime.now(timezone.utc)
        _end_sessions(db, target)
        db.commit()
        audit_service.log_action(db, str(admin.id), "user_deactivated", "user", str(target.id), f"role={target.role}")


@moved(router, canonical, "POST", "/users/{user_id}/reactivate", "/users/{user_id}/reactivate", status_code=204)
@limiter.limit("20/hour")
def reactivate_user(
    request: Request, user_id: uuid.UUID,
    admin: User = Depends(require_admin), _proof: None = Depends(fresh_proof("reactivate this account")),
    db: Session = Depends(get_db),
):
    target = _target(db, user_id)
    if not target.is_active:
        target.is_active = True
        target.deactivated_at = None
        db.commit()
        _clear_failures(db, target)
        audit_service.log_action(db, str(admin.id), "user_reactivated", "user", str(target.id), f"role={target.role}")


@moved(router, canonical, "PATCH", "/users/{user_id}/role", "/users/{user_id}/role", status_code=204)
@limiter.limit("20/hour")
def change_role(
    request: Request, user_id: uuid.UUID, body: RoleChange,
    admin: User = Depends(require_admin), _proof: None = Depends(fresh_proof("change this account's role")),
    db: Session = Depends(get_db),
):
    lock_admins(db)
    target = _target(db, user_id)
    _not_self(admin, target, "change the role of")
    if body.role != target.role:
        if target.role == "admin":
            _last_admin_guard(db, target, "demoted")
        old = target.role
        target.role = body.role
        db.commit()
        audit_service.log_action(db, str(admin.id), "user_role_changed", "user", str(target.id), f"{old}->{body.role}")


@moved(router, canonical, "POST", "/users/{user_id}/clear-two-step", "/users/{user_id}/clear-two-step", status_code=204)
@limiter.limit("20/hour")
def clear_two_step(
    request: Request, user_id: uuid.UUID,
    admin: User = Depends(require_admin), _proof: None = Depends(fresh_proof("clear this account's two-step sign-in")),
    db: Session = Depends(get_db),
):
    """For a lost authenticator. Two-step is switched off and every session of the account ends, so the person signs in
    again with their password and can enrol a new authenticator."""
    target = _target(db, user_id)
    if target.totp_enabled or target.totp_secret:
        target.totp_enabled = False
        target.totp_secret = None
        target.totp_last_step = None
        _end_sessions(db, target)
        db.commit()
        audit_service.log_action(db, str(admin.id), "user_two_step_cleared", "user", str(target.id), "")


def _password_marker(user: User) -> str:
    # changes whenever the password does, so a reset link works once: using it changes the marker the link carries
    return hashlib.sha256((user.password_hash or "").encode()).hexdigest()[:16]


@moved(router, canonical, "POST", "/users/{user_id}/reset-link", "/users/{user_id}/reset-link", response_model=ResetLinkSent)
@limiter.limit("20/hour")
def send_reset_link(
    request: Request, user_id: uuid.UUID,
    admin: User = Depends(require_admin), _proof: None = Depends(fresh_proof("send a password reset link")),
    db: Session = Depends(get_db),
):
    """Email the account a one-time link to choose a new password. The link goes only to the account's own address and is
    never returned to the admin, so an admin cannot use it to take the account over."""
    target = _target(db, user_id)
    if target.is_service:
        raise ApiError(409, Code.SERVICE_ACCOUNT_REFUSED, "A service account has no password to reset. Make it a new API token instead")
    if not target.is_active:
        raise ApiError(409, Code.ACCOUNT_DEACTIVATED, "This account is deactivated. Reactivate it first")
    if not signin_guard.store.set_nx(f"reset-sent:{target.id}", 600):
        raise ApiError(429, Code.RESET_LINK_RECENT, "A reset link was sent a moment ago. Try again in a few minutes", headers={"Retry-After": "600"})
    token = _encode({"sub": str(target.id), "ver": target.token_version or 0, "pw": _password_marker(target)},
                    "reset", timedelta(hours=_RESET_HOURS))
    link = f"{settings.dashboard_url.rstrip('/')}/reset-password#token={token}"
    sent = email_service.send_password_reset(target.email, link)
    if not sent:
        raise ApiError(503, Code.EMAIL_NOT_SENT, "The email could not be sent, so no reset link was made available")
    audit_service.log_action(db, str(admin.id), "password_reset_link_sent", "user", str(target.id), "")
    note = "A reset link was sent to the account's own address"
    # `detail` repeats `message` for this release. A success body does not use it any more
    return ResetLinkSent(message=note, detail=note, email_sent=True)


@moved(router, canonical, "DELETE", "/users/{user_id}", "/users/{user_id}", status_code=204)
@limiter.limit("10/hour")
def remove_user(
    request: Request, user_id: uuid.UUID,
    admin: User = Depends(require_admin), _proof: None = Depends(fresh_proof("remove this account")),
    db: Session = Depends(get_db),
):
    """Remove an account. Its tickets stay with the person taken off them, its sessions go with it and the audit trail is
    kept (it holds the account's id and no address). An account that still owns machines is refused until they are handed on."""
    lock_admins(db)
    target = _target(db, user_id)
    _not_self(admin, target, "remove")
    _refuse_if_account_cannot_go(db, target)
    role = target.role
    remove_account(db, target)
    audit_service.log_action(db, str(admin.id), "user_removed", "user", str(user_id), f"role={role}")


@moved(router, canonical, "GET", "/invitations", "/invitations", response_model=list[InvitationSummary])
@limiter.limit("60/minute")
def list_invitations(
    request: Request, response: Response,
    _admin: User = Depends(require_admin), _session: User = Depends(session_only),
    page: Page = Depends(Page), db: Session = Depends(get_db),
):
    """The invitations that can still be used: not used, not cancelled and not expired."""
    now = datetime.now(timezone.utc)
    query = db.query(Invitation).filter(Invitation.used_at.is_(None), Invitation.cancelled_at.is_(None), Invitation.expires_at > now)
    set_total(response, query.count())
    rows = query.order_by(Invitation.created_at.desc(), Invitation.id).offset(page.offset).limit(page.limit).all()
    names = {u.id: u.name for u in db.query(User).filter(User.id.in_([r.invited_by for r in rows if r.invited_by])).all()} if rows else {}
    return [
        InvitationSummary(
            id=r.id, email=r.email, role=r.role, invited_by_name=names.get(r.invited_by),
            created_at=r.created_at, expires_at=r.expires_at,
        )
        for r in rows
    ]


@canonical.post("/service-accounts", status_code=201, response_model=UserSummary, operation_id="create_service_account")
@limiter.limit(named("sensitive"))
def create_service_account(
    request: Request, payload: ServiceAccountCreate,
    admin: User = Depends(require_admin), _proof: None = Depends(fresh_proof("make a service account")),
    db: Session = Depends(get_db),
):
    """Make an account for an integration. It has a role and no way to sign in and it owns API tokens, so a script does not
    stop when the person who set it up leaves. Its tokens are made with `POST /tokens` and an `account_id`, by an admin with
    fresh proof. It has no password, provider link, two-step, session, invitation or reset link and the sign-in route answers
    for it exactly as for an unknown address."""
    # the address is made up and never receives mail. No route sends email to a service account
    account = User(
        name=payload.name, email=f"svc-{secrets.token_hex(6)}@service.example.com", role=payload.role,
        password_hash=None, is_service=True, is_active=True,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    audit_service.log_action(db, str(admin.id), "service_account_created", "user", str(account.id), f"role={account.role}")
    return UserSummary.model_validate(account)


@moved(router, canonical, "DELETE", "/invitations/{invitation_id}", "/invitations/{invitation_id}", status_code=204)
@limiter.limit("30/hour")
def cancel_invitation(
    request: Request, invitation_id: uuid.UUID,
    admin: User = Depends(require_admin), _proof: None = Depends(fresh_proof("cancel this invitation")),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    row = (
        db.query(Invitation)
        .filter(Invitation.id == invitation_id, Invitation.used_at.is_(None), Invitation.cancelled_at.is_(None), Invitation.expires_at > now)
        .with_for_update()
        .first()
    )
    if row is None:
        raise ApiError(404, Code.INVITATION_NOT_FOUND, "Invitation not found")
    row.cancelled_at = now
    db.commit()
    audit_service.log_action(db, str(admin.id), "invitation_cancelled", "invitation", str(row.id), f"role={row.role}")


@router.post("/reset-password", status_code=204)
@limiter.limit("10/minute")
def reset_password(request: Request, payload: ResetPassword, db: Session = Depends(get_db)):
    """Choose a new password with a link an admin sent. The link works once and ends every session of the account.

    Every refusal is the same answer, so nothing is learned about the link or the account from it.
    """
    refused = ApiError(400, Code.RESET_LINK_INVALID, "This reset link is invalid or has expired")
    try:
        claims = decode_token(payload.token, "reset")
        user = db.query(User).filter(User.id == uuid.UUID(str(claims["sub"]))).with_for_update().first()
    except (HTTPException, ValueError):
        raise refused
    if (
        user is None or not user.is_active or user.is_service
        or claims.get("ver", 0) != (user.token_version or 0)
        or claims.get("pw") != _password_marker(user)
    ):
        raise refused
    user.password_hash = hash_password(payload.password)
    _end_sessions(db, user)
    db.commit()
    _clear_failures(db, user)
    audit_service.log_action(db, str(user.id), "password_reset", "user", str(user.id), "")
