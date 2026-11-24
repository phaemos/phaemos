from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Page, set_total
from app.errors import ApiError, Code
from app.limiter import limiter
from app.models.user import User
from app.models.webhook import Webhook
from app.patching import apply_patch
from app.routes.auth import fresh_proof, require_admin
from app.schemas.webhook import WebhookCreate, WebhookResponse, WebhookTestResult, WebhookUpdate, WebhookWithSecret
from app.services import idempotency, webhook_secrets, webhook_service
from app.services.url_safety import UnsafeUrl, check_outbound_url

router = APIRouter()


def _check_address(url: str) -> None:
    # an admin could otherwise make the API call a service inside its own network
    try:
        check_outbound_url(url)
    except UnsafeUrl as exc:
        raise ApiError(422, Code.WEBHOOK_URL_REFUSED, str(exc)) from None


def _check_template(template: str | None, fmt: str) -> None:
    if template is None:
        return
    if fmt == "json":
        raise ApiError(422, Code.WEBHOOK_TEMPLATE_INVALID, "A json webhook sends the event body and takes no template. Leave template out")
    try:
        webhook_service.check_template(template)
    except ValueError as exc:
        raise ApiError(422, Code.WEBHOOK_TEMPLATE_INVALID, str(exc)) from None


def _find(db: Session, webhook_id: UUID) -> Webhook:
    wh = db.query(Webhook).filter(Webhook.id == webhook_id).first()
    if not wh:
        raise ApiError(404, Code.WEBHOOK_NOT_FOUND, "Webhook not found")
    return wh


def _with_secret(wh: Webhook, secret: str | None) -> WebhookWithSecret:
    out = WebhookWithSecret.model_validate(wh)
    out.secret = secret
    return out


@router.get("/webhooks", response_model=list[WebhookResponse])
def list_webhooks(
    response: Response,
    enabled: bool | None = None,
    page: Page = Depends(Page),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(Webhook)
    if enabled is not None:
        q = q.filter(Webhook.enabled == enabled)
    set_total(response, q.count())
    return q.order_by(Webhook.created_at.desc(), Webhook.id.desc()).offset(page.offset).limit(page.limit).all()


@router.get("/webhooks/{webhook_id}", response_model=WebhookResponse)
def get_webhook(
    webhook_id: UUID,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return _find(db, webhook_id)


@router.post("/webhooks", response_model=WebhookWithSecret, status_code=201)
def create_webhook(
    body: WebhookCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    admin: User = Depends(require_admin),
    _proof: None = Depends(fresh_proof("add a webhook")),
    db: Session = Depends(get_db),
):
    # the secret is in the stored answer, which is encrypted, so a repeat after a lost answer still gets it
    idem = idempotency.begin(admin.id, "POST /webhooks", idempotency_key, body)
    if idem.replay is not None:
        return idem.replay
    with idem:
        _check_address(str(body.url))
        _check_template(body.template, body.format)
        secret = webhook_secrets.new_secret() if body.format == "json" else None
        wh = Webhook(name=body.name, url=str(body.url), enabled=body.enabled, template=body.template, format=body.format, secret=secret)
        db.add(wh)
        db.commit()
        db.refresh(wh)
        out = _with_secret(wh, secret)
        idem.save(201, out.model_dump(mode="json"))
    return out


@router.patch("/webhooks/{webhook_id}", response_model=WebhookWithSecret)
def update_webhook(
    webhook_id: UUID,
    body: WebhookUpdate,
    _admin: User = Depends(require_admin),
    _proof: None = Depends(fresh_proof("change a webhook")),
    db: Session = Depends(get_db),
):
    wh = _find(db, webhook_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("url") is not None:
        changes["url"] = str(changes["url"])
        _check_address(changes["url"])
    if changes.get("enabled"):
        # switching one back on checks its address again and clears the reason it was switched off
        _check_address(changes.get("url") or wh.url)
        wh.disabled_reason = None
        wh.consecutive_failures = 0
    new_format = changes.get("format") or wh.format
    new_template = changes["template"] if "template" in changes else wh.template
    if new_format == "json" and "template" in changes and changes["template"] is not None:
        _check_template(changes["template"], "json")
    elif "template" in changes:
        _check_template(changes["template"], new_format)
    # a field left out is kept. template may be cleared with null (the built-in message). Any other null is a 422
    apply_patch(wh, changes, clearable={"template"})
    secret = None
    if wh.format == "json" and not wh.secret:
        # a webhook that becomes json gets its secret now, shown once
        secret = webhook_secrets.new_secret()
        wh.secret = secret
        if new_template is not None:
            wh.template = None
    elif wh.format != "json" and wh.secret:
        wh.secret = None
    db.commit()
    db.refresh(wh)
    return _with_secret(wh, secret)


@router.post("/webhooks/{webhook_id}/rotate-secret", response_model=WebhookWithSecret)
def rotate_webhook_secret(
    webhook_id: UUID,
    _admin: User = Depends(require_admin),
    _proof: None = Depends(fresh_proof("rotate a webhook secret")),
    db: Session = Depends(get_db),
):
    """A new signing secret for a json webhook, shown once. The old one stops signing at once, so update the receiver first or at once."""
    wh = _find(db, webhook_id)
    if wh.format != "json":
        raise ApiError(422, Code.WEBHOOK_NOT_JSON, "Only a json webhook has a signing secret")
    secret = webhook_secrets.new_secret()
    wh.secret = secret
    db.commit()
    db.refresh(wh)
    return _with_secret(wh, secret)


@router.delete("/webhooks/{webhook_id}", status_code=204)
def delete_webhook(
    webhook_id: UUID,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    wh = _find(db, webhook_id)
    db.delete(wh)
    db.commit()


@router.post("/webhooks/{webhook_id}/test", response_model=WebhookTestResult)
@limiter.limit("10/minute")
def test_webhook(
    request: Request,
    webhook_id: UUID,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Send one test delivery and say what happened. 200 with the status and the time taken when the receiver accepted it. A failure is
    not a 200: 502 `webhook_delivery_failed` and `errors` holds {"status", "elapsed_ms"}.
    """
    wh = _find(db, webhook_id)
    # an address saved before the check existed is refused here too
    _check_address(wh.url)
    outcome = webhook_service.test_webhook(wh)
    if not outcome.ok:
        reason = f"HTTP {outcome.status}" if outcome.status else (outcome.error or "no answer")
        raise ApiError(
            502, Code.WEBHOOK_DELIVERY_FAILED, f"The test delivery failed ({reason}) after {outcome.elapsed_ms} ms",
            errors=[{"status": outcome.status, "elapsed_ms": outcome.elapsed_ms}],
        )
    return WebhookTestResult(ok=True, status=outcome.status, elapsed_ms=outcome.elapsed_ms)
