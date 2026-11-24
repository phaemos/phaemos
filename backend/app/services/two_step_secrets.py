"""
Two-step secrets encrypted at rest.

A two-step secret was stored as plain text, so one database read or one backup file gave every secret and with it every
second factor. It is now stored as `enc:v1:<token>`, a Fernet token (AES-128-CBC with an HMAC) under a key derived for
this purpose from SECRET_KEY (`derive_key("two_step_secret")`). SECRET_KEY_PREVIOUS is tried for reading after a key
rotation and `encrypt_legacy` writes everything back under the current key.

A row that is not yet encrypted (a database from before migration 032) is read as it is and encrypted on the next start
or by `python -m app.scripts.encrypt_two_step_secrets`. Running either twice changes nothing.
"""

import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.types import Text, TypeDecorator

from app.services.keys import fernet_keys

logger = logging.getLogger(__name__)

PREFIX = "enc:v1:"


def _multi() -> MultiFernet:
    return MultiFernet([Fernet(k) for k in fernet_keys("two_step_secret")])


def encrypt(plain: str) -> str:
    return PREFIX + _multi().encrypt(plain.encode()).decode()


def decrypt(value: str) -> str:
    """The secret in clear. A value without the prefix is a row that was never encrypted and is returned as it is."""
    if not value.startswith(PREFIX):
        return value
    return _multi().decrypt(value[len(PREFIX):].encode()).decode()


class EncryptedSecret(TypeDecorator):
    """A text column that is encrypted on the way in and decrypted on the way out."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or value.startswith(PREFIX):
            return value
        return encrypt(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return decrypt(value)
        except InvalidToken:
            # neither key opens it. The secret is unusable, so two-step cannot be passed until an admin clears it
            logger.error("a stored two-step secret could not be decrypted with the current or the previous key")
            return None


def encrypt_legacy(db: Session) -> int:
    """Encrypt every secret still in clear and re-encrypt any made under the previous key. Returns rows changed."""
    changed = 0
    current = Fernet(fernet_keys("two_step_secret")[0])
    rows = db.execute(text("SELECT id, totp_secret FROM users WHERE totp_secret IS NOT NULL")).all()
    for row_id, stored in rows:
        if stored.startswith(PREFIX):
            try:
                current.decrypt(stored[len(PREFIX):].encode())
                continue                       # already under the current key
            except InvalidToken:
                try:
                    plain = decrypt(stored)    # under the previous key
                except InvalidToken:
                    continue
        else:
            plain = stored
        db.execute(text("UPDATE users SET totp_secret = :s WHERE id = :i"), {"s": encrypt(plain), "i": row_id})
        changed += 1
    if changed:
        db.commit()
    return changed
