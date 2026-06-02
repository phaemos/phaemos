from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.models.webhook import Webhook
from app.routes.auth import require_admin
from app.services import webhook_service

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class WebhookCreate(BaseModel):
    name: str
    url: HttpUrl
    enabled: bool = True
    template: str | None = None


class WebhookUpdate(BaseModel):
    name: str | None = None
    url: HttpUrl | None = None
    enabled: bool | None = None
    template: str | None = None


class WebhookResponse(BaseModel):
    id: UUID
    name: str
    url: str
    enabled: bool
    template: str | None

    model_config = {"from_attributes": True}


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("/webhooks", response_model=list[WebhookResponse])
def list_webhooks(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return db.query(Webhook).order_by(Webhook.created_at.desc()).all()


@router.post("/webhooks", response_model=WebhookResponse, status_code=201)
def create_webhook(
    body: WebhookCreate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    wh = Webhook(name=body.name, url=str(body.url), enabled=body.enabled, template=body.template)
    db.add(wh)
    db.commit()
    db.refresh(wh)
    return wh


@router.patch("/webhooks/{webhook_id}", response_model=WebhookResponse)
def update_webhook(
    webhook_id: UUID,
    body: WebhookUpdate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    wh = db.query(Webhook).filter(Webhook.id == webhook_id).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")
    for field, value in body.model_dump(exclude_none=True).items():
        if field == "url" and value is not None:
            value = str(value)
        setattr(wh, field, value)
    db.commit()
    db.refresh(wh)
    return wh


@router.delete("/webhooks/{webhook_id}", status_code=204)
def delete_webhook(
    webhook_id: UUID,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    wh = db.query(Webhook).filter(Webhook.id == webhook_id).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")
    db.delete(wh)
    db.commit()


@router.post("/webhooks/{webhook_id}/test", status_code=200)
def test_webhook(
    webhook_id: UUID,
    background_tasks: BackgroundTasks,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    wh = db.query(Webhook).filter(Webhook.id == webhook_id).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")
    # I run the test delivery in a background task so the response is instant.
    ok = webhook_service.test_webhook(wh)
    return {"success": ok}
