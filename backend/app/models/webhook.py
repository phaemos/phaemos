import uuid
from sqlalchemy import Boolean, Column, Integer, String, DateTime, Text, func
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base
from app.services.webhook_secrets import EncryptedWebhookSecret


class Webhook(Base):
    __tablename__ = "webhooks"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name       = Column(String(200), nullable=False)
    url        = Column(Text, nullable=False)
    enabled    = Column(Boolean, default=True, nullable=False)
    # allow a custom message template with {device_name}, {metric}, {value},
    # {threshold}, {severity} placeholders; NULL means use the built-in format.
    template   = Column(Text, nullable=True)
    # set when delivery switches the webhook off because its address is no longer safe to call
    disabled_reason = Column(Text, nullable=True)
    # chat: a message for Slack, Discord or Teams (chosen by the address). json: the event body, signed (migration 036)
    format     = Column(String(10), nullable=False, default="chat", server_default="chat")
    # the signing secret of a json webhook, encrypted. Shown once when it is made or rotated and never returned again
    secret     = Column(EncryptedWebhookSecret, nullable=True)
    # delivery state, kept by the delivery itself: when it last tried, what the last answer was (the HTTP status or null with
    # last_error when nothing answered) and how many deliveries in a row failed after their tries
    last_delivery_at     = Column(DateTime(timezone=True), nullable=True)
    last_status          = Column(Integer, nullable=True)
    last_error           = Column(String(40), nullable=True)
    consecutive_failures = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    @property
    def has_secret(self) -> bool:
        return bool(self.secret)
