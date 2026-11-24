"""
Confirming the phone number that alert texts go to.

A critical alert is sent by text to the number on an account and anyone with a token could once point those texts at any
number. A number now receives alerts only after a six digit code sent to that number has been typed back. A changed number
starts unconfirmed.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.errors import ApiError, Code
from app.config import settings
from app.db import get_db
from app.limiter import limiter
from app.models.user import User
from app.routes.auth import get_current_user
from app.services import audit_service, signin_guard, sms_service
from app.services.keys import derive_key

router = APIRouter()

CODE_MINUTES = 10
MAX_WRONG_TRIES = 5
SENDS_PER_ACCOUNT_PER_HOUR = 5
SENDS_PER_NUMBER_PER_HOUR = 3


class PhoneCode(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


def _hash(user: User, number: str, code: str) -> str:
    # keyed and bound to the account and the number, so a code cannot be used for another number or account
    return hmac.new(derive_key("phone_code"), f"{user.id}:{number}:{code}".encode(), hashlib.sha256).hexdigest()


class PhoneCodeSent(BaseModel):
    sent: bool
    message: str
    # repeats `message` for this release. A success body does not use `detail` any more
    detail: str
    expires_in_seconds: int | None = None


@router.post("/me/phone/send-code", response_model=PhoneCodeSent)
@limiter.limit("10/hour")
def send_phone_code(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Send a six digit code by text to the account's current number. It expires after 10 minutes and allows 5 wrong tries."""
    number = user.phone_number
    if not number:
        raise ApiError(400, Code.PHONE_MISSING, "Add a phone number to your profile first")
    # a limit for each account and for each number, so neither a person nor a number can be used to send many texts
    number_key = hashlib.sha256(number.encode()).hexdigest()[:32]
    if (
        signin_guard.store.incr(f"phone-send:acct:{user.id}", 3600) > SENDS_PER_ACCOUNT_PER_HOUR
        or signin_guard.store.incr(f"phone-send:num:{number_key}", 3600) > SENDS_PER_NUMBER_PER_HOUR
    ):
        raise ApiError(429, Code.PHONE_CODES_LIMIT, "Too many codes. Try again in an hour", headers={"Retry-After": "3600"})
    if not sms_service.is_configured() and not settings.is_development:
        # nothing is stored, because no code could reach the person
        raise ApiError(503, Code.TEXTS_NOT_SET_UP, "Texts are not set up on this server, so a confirmation code cannot be sent")
    code = f"{secrets.randbelow(1_000_000):06d}"
    user.phone_code_hash = _hash(user, number, code)
    user.phone_code_number = number
    user.phone_code_expires_at = datetime.now(timezone.utc) + timedelta(minutes=CODE_MINUTES)
    user.phone_code_attempts = 0
    db.commit()
    sent = sms_service.send_sms(number, f"PHAEMOS confirmation code: {code}. It expires in {CODE_MINUTES} minutes.")
    if not sent:
        if sms_service.is_configured():
            raise ApiError(502, Code.TEXT_NOT_SENT, "The text could not be sent. Try again later")
        # development with no text vendor: say a code was issued and show it only when asked to
        import logging
        log = logging.getLogger(__name__)
        # the account is named by its id and the number stays out of the log, even masked. This branch is
        # reached only in development (production with no vendor stopped above), so the code is shown on request
        if settings.log_email_bodies:
            log.info("A phone confirmation code was issued for account %s: %s", user.id, code)
        else:
            log.info("A phone confirmation code was issued for account %s (set LOG_EMAIL_BODIES to log it)", user.id)
        note = "No text vendor is configured. The code was issued but not sent"
        return PhoneCodeSent(sent=False, message=note, detail=note)
    note = "A code was sent to your number"
    return PhoneCodeSent(sent=True, message=note, detail=note, expires_in_seconds=CODE_MINUTES * 60)


@router.post("/me/phone/confirm", status_code=204)
@limiter.limit("30/hour")
def confirm_phone(request: Request, body: PhoneCode, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Confirm the number with the code that was texted to it. After 5 wrong tries the code is gone and a new one is needed."""
    bad = ApiError(400, Code.PHONE_CODE_WRONG, "That code is wrong or has expired")
    now = datetime.now(timezone.utc)
    if (
        not user.phone_code_hash or user.phone_code_number != user.phone_number
        or user.phone_code_expires_at is None or user.phone_code_expires_at <= now
    ):
        raise bad
    if not hmac.compare_digest(user.phone_code_hash, _hash(user, user.phone_number, body.code)):
        user.phone_code_attempts = (user.phone_code_attempts or 0) + 1
        if user.phone_code_attempts >= MAX_WRONG_TRIES:
            user.phone_code_hash = user.phone_code_number = user.phone_code_expires_at = None
        db.commit()
        raise bad
    user.phone_confirmed_at = now
    user.phone_code_hash = user.phone_code_number = user.phone_code_expires_at = None
    user.phone_code_attempts = 0
    db.commit()
    audit_service.log_action(db, str(user.id), "phone_confirmed", "user", str(user.id), "")
