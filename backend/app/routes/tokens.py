"""
API tokens: a way for a script, a service or the command line tool to use the API without a person's password.

A token belongs to one account and is shown once, when it is made. Only a keyed hash is kept. It is sent as
`Authorization: Bearer pht_...`. What a token may do is decided in one place (get_current_user and
app/services/token_access.py): making or revoking a token needs a signed-in session and so does everything about the
account's own security. The one thing a token may do to tokens is revoke itself (`DELETE /tokens/current`).

An admin can also make a token for a service account (`account_id` on `POST /tokens`), so an integration does not stop when
the person who set it up leaves. The audit rows name the admin who made it and the token that acted.

The routes live at /tokens. The older /auth/tokens paths are deprecated aliases for this release.
"""

import re
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Page, set_total
from app.errors import ApiError, Code
from app.limiter import limiter
from app.models.api_token import ApiToken
from app.models.user import User
from app.routes.auth import fresh_proof, get_current_user, session_only
from app.routes.moved import moved
from app.schemas.token import TokenCreate, TokenCreated, TokenSummary, Whoami, WhoamiToken
from app.services import audit_service, token_access

router = APIRouter()       # the old /auth paths and /auth/whoami
canonical = APIRouter()    # /tokens


def _summary(row: ApiToken) -> TokenSummary:
    return TokenSummary(
        id=row.id, name=row.name, scope=row.scope, created_at=row.created_at, expires_at=row.expires_at,
        last_used_at=row.last_used_at, account_id=row.user_id, created_by=row.created_by,
    )


def _service_account(request: Request, db: Session, caller: User, account_id: UUID | None) -> User:
    """The account a token is made for or listed for: the caller or a service account when the caller is an admin."""
    if account_id is None or account_id == caller.id:
        return caller
    target = db.get(User, account_id)
    # the token's own scope counts, not only the account's role: a read token on an admin account is not an admin
    if not token_access.acts_as_admin(request, caller):
        raise ApiError(403, Code.ADMIN_REQUIRED, "Only an admin can manage the tokens of a service account")
    if target is None or not target.is_service:
        # a person's own account is never reachable this way and nothing says whether the id is a person
        raise ApiError(404, Code.USER_NOT_FOUND, "No such service account")
    return target


@moved(router, canonical, "POST", "/tokens", "/tokens", status_code=201, response_model=TokenCreated)
@limiter.limit("10/hour")
def create_token(
    request: Request,
    payload: TokenCreate,
    user: User = Depends(get_current_user),
    _proof: None = Depends(fresh_proof("create an API token", admin_only=False)),
    db: Session = Depends(get_db),
):
    """Make an API token for yourself or for a service account when you are an admin. The answer holds the token itself and
    it is never shown again."""
    owner = _service_account(request, db, user, payload.account_id)
    if payload.scope == "admin" and owner.role != "admin":
        raise ApiError(403, Code.TOKEN_SCOPE_FORBIDDEN, "Only an admin account can have an admin token")
    now = datetime.now(timezone.utc)
    # the account row is locked so two requests together cannot both pass the count
    db.query(User).filter(User.id == owner.id).with_for_update().first()
    live = db.query(ApiToken).filter(
        ApiToken.user_id == owner.id, ApiToken.revoked_at.is_(None), ApiToken.expires_at > now
    ).count()
    if live >= token_access.MAX_TOKENS_PER_ACCOUNT:
        raise ApiError(409, Code.TOKEN_LIMIT, f"There are already {token_access.MAX_TOKENS_PER_ACCOUNT} live API tokens. Revoke one first")
    token_id, secret, token = token_access.new_token()
    row = ApiToken(
        id=token_id,
        user_id=owner.id,
        name=payload.name,
        scope=payload.scope,
        secret_hash=token_access.hashes(secret)[0],
        token_version=owner.token_version or 0,
        created_at=now,
        expires_at=now + timedelta(days=payload.expires_in_days),
        created_by=user.id,
    )
    db.add(row)
    db.commit()
    for_whom = f"; account={owner.id}" if owner.id != user.id else ""
    audit_service.log_action(db, str(user.id), "token_created", "api_token", token_id, f"scope={payload.scope}; name={payload.name}{for_whom}")
    return TokenCreated(
        id=row.id, name=row.name, scope=row.scope, created_at=row.created_at, expires_at=row.expires_at,
        account_id=owner.id, token=token,
    )


@moved(router, canonical, "GET", "/tokens", "/tokens", response_model=list[TokenSummary])
@limiter.limit("60/minute")
def list_tokens(
    request: Request,
    response: Response,
    account_id: UUID | None = None,
    user: User = Depends(get_current_user),
    page: Page = Depends(Page),
    db: Session = Depends(get_db),
):
    """The tokens of the account (or, for an admin, of a service account with `account_id`) that are not revoked, newest first.
    Never the secret. An expired token is listed until it is revoked."""
    owner = _service_account(request, db, user, account_id)
    query = db.query(ApiToken).filter(ApiToken.user_id == owner.id, ApiToken.revoked_at.is_(None))
    set_total(response, query.count())
    rows = query.order_by(ApiToken.created_at.desc(), ApiToken.id).offset(page.offset).limit(page.limit).all()
    return [_summary(row) for row in rows]


@token_access.token_self_service_marker
def _calling_token(request: Request, user: User = Depends(get_current_user)) -> ApiToken:
    """The API token making this call. A session has none."""
    row = getattr(request.state, "api_token", None)
    if row is None:
        raise ApiError(400, Code.NO_TOKEN_IN_USE, "No API token is in use. Revoke a token by its id instead")
    return row


# declared before /tokens/{token_id} so "current" is not read as an id
@canonical.delete("/tokens/current", status_code=204, operation_id="revoke_current_token")
@limiter.limit("30/hour")
def revoke_current_token(request: Request, row: ApiToken = Depends(_calling_token), db: Session = Depends(get_db)):
    """The API token that makes this call revokes itself. It is the only thing a token may do to tokens."""
    row.revoked_at = datetime.now(timezone.utc)
    db.commit()
    audit_service.log_action(db, str(row.user_id), "token_revoked", "api_token", row.id, "by itself")


@moved(router, canonical, "DELETE", "/tokens/{token_id}", "/tokens/{token_id}", status_code=204)
@limiter.limit("30/hour")
def revoke_token(request: Request, token_id: str, user: User = Depends(session_only), db: Session = Depends(get_db)):
    """Revoke a token of the account or as an admin one of a service account's. Another person's token answers 404."""
    row = db.get(ApiToken, token_id) if re.fullmatch(r"[0-9a-f]{12}", token_id) else None
    if row is not None and row.user_id != user.id:
        owner = db.get(User, row.user_id)
        if user.role != "admin" or owner is None or not owner.is_service:
            row = None
    if row is None or row.revoked_at is not None:
        raise ApiError(404, Code.TOKEN_NOT_FOUND, "Token not found")
    row.revoked_at = datetime.now(timezone.utc)
    db.commit()
    audit_service.log_action(db, str(user.id), "token_revoked", "api_token", row.id, "" if row.user_id == user.id else f"account={row.user_id}")


@router.get("/whoami", response_model=Whoami, operation_id="whoami")
@limiter.limit("120/minute")
def whoami(request: Request, user: User = Depends(get_current_user)):
    """Who is calling and how they signed in."""
    row = getattr(request.state, "api_token", None)
    return Whoami(
        id=user.id, role=user.role, signed_in_with="token" if row is not None else "session", is_service=bool(user.is_service),
        token=None if row is None else WhoamiToken(id=row.id, name=row.name, scope=row.scope, expires_at=row.expires_at),
    )
