"""
A webhook's signing secret, encrypted at rest.

The secret has to be read back to sign each delivery, so it cannot be a one-way hash like a device key or an API token. It is
stored as `enc:v1:<token>`, a Fernet token (AES-128-CBC with an HMAC) under a key derived for this one purpose from SECRET_KEY
(services/keys.py, purpose "webhook_secret"). SECRET_KEY_PREVIOUS is tried for reading after a rotation of the server key, so
a rotation does not silence a webhook. A copy of the database alone cannot sign a delivery. The secret is shown once, when it is
made or rotated and no route returns it again.
"""

import logging
import secrets

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy.types import Text, TypeDecorator

from app.services.keys import fernet_keys

logger = logging.getLogger(__name__)

PREFIX = "enc:v1:"
SECRET_PREFIX = "whsec_"


def new_secret() -> str:
    return SECRET_PREFIX + secrets.token_urlsafe(32)


def _multi() -> MultiFernet:
    return MultiFernet([Fernet(k) for k in fernet_keys("webhook_secret")])


class EncryptedWebhookSecret(TypeDecorator):
    """A text column encrypted on the way in and decrypted on the way out. An unreadable value comes back as None."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or value.startswith(PREFIX):
            return value
        return PREFIX + _multi().encrypt(value.encode()).decode()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return _multi().decrypt(value[len(PREFIX):].encode()).decode() if value.startswith(PREFIX) else value
        except InvalidToken:
            logger.error("a webhook secret could not be decrypted with the current or the previous key")
            return None
