from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl

WebhookFormat = Literal["chat", "json"]


class WebhookCreate(BaseModel):
    # the column holds 200 characters
    name: str = Field(max_length=200)
    url: HttpUrl
    enabled: bool = True
    # chat: a message for Slack, Discord or Teams (by the address). json: the signed event body, with a secret shown once
    format: WebhookFormat = "chat"
    # a chat message with {device_name}, {metric}, {value}, {threshold} and {severity}. Checked when it is saved. Not for json
    template: str | None = Field(default=None, max_length=1000)


class WebhookUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    url: HttpUrl | None = None
    enabled: bool | None = None
    format: WebhookFormat | None = None
    # null puts the built-in message back
    template: str | None = Field(default=None, max_length=1000)


class WebhookResponse(BaseModel):
    id: UUID
    name: str
    url: str
    enabled: bool
    format: WebhookFormat = "chat"
    template: str | None
    # why delivery switched this webhook off. Null when it has not been
    disabled_reason: str | None = None
    # a json webhook has a signing secret. It is shown once (WebhookWithSecret) and never again
    has_secret: bool = False
    # the outcome of the last delivery: when, the HTTP status (null when nothing answered) and a short reason when it failed and how
    # many deliveries in a row failed after their tries
    last_delivery_at: datetime | None = None
    last_status: int | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class WebhookWithSecret(WebhookResponse):
    # present only in the answer that makes or rotates the secret. Store it now: it cannot be read back
    secret: str | None = None


class WebhookTestResult(BaseModel):
    ok: bool
    # the HTTP status the receiver answered
    status: int | None = None
    elapsed_ms: int
