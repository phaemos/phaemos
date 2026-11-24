"""
One key for each purpose, derived from SECRET_KEY.

A single key that signs access tokens, refresh tokens, invitations, resets, the audit export and encrypts stored
secrets means that a leak or a bug in one use breaks all of them and that a token made for one purpose can be
replayed as another. Each purpose here gets its own key: HKDF-SHA256 (RFC 5869) of SECRET_KEY with the purpose as
the context. The same purpose always gives the same key and two purposes never share one.

    from app.services.keys import derive_key
    key = derive_key("model_file")        # 32 bytes

SECRET_KEY_PREVIOUS is the key before a rotation. It is used to verify a token or decrypt a stored value that the
current key does not accept, never to sign or encrypt, so the key can be rotated without signing everyone out.
"""

import base64
import hashlib
import hmac

from app.config import settings

# the purposes in use. A new one is added here so the full list is in one place
PURPOSES = (
    "access", "refresh", "challenge", "link", "reset", "device",   # signed tokens
    "audit_export",                                                  # the HMAC over the audit CSV
    "two_step_secret",                                               # encryption of stored two-step secrets
    "model_file",                                                    # the HMAC beside the saved model
    "webhook_secret",                                                # the encryption of a webhook's signing secret
    "idempotency",                                                   # the encryption of a stored Idempotency-Key answer
    "device_key",                                                    # the keyed hash of a device API key (services/device_keys.py)
    "api_token",                                                     # the keyed hash of an access token secret (routes/tokens.py)
    "phone_code",                                                    # the hash of a text confirmation code
)


def _hkdf(secret: bytes, purpose: str, length: int = 32) -> bytes:
    # extract with a fixed, public salt, then expand with the purpose as the info string
    prk = hmac.new(b"phaemos-hkdf-salt-v1", secret, hashlib.sha256).digest()
    out, block, counter = b"", b"", 1
    while len(out) < length:
        block = hmac.new(prk, block + purpose.encode() + bytes([counter]), hashlib.sha256).digest()
        out += block
        counter += 1
    return out[:length]


def derive_key(purpose: str, previous: bool = False) -> bytes:
    """The 32 byte key for a purpose. previous=True derives it from SECRET_KEY_PREVIOUS instead."""
    if purpose not in PURPOSES:
        raise ValueError(f"unknown key purpose {purpose!r}")
    secret = settings.secret_key_previous if previous else settings.secret_key
    if not secret:
        raise ValueError("no previous key is set")
    return _hkdf(secret.encode(), purpose)


def verification_keys(purpose: str) -> list[bytes]:
    """The keys a token or value may be checked with: the current key first, then the previous one if set."""
    keys = [derive_key(purpose)]
    if settings.secret_key_previous:
        keys.append(derive_key(purpose, previous=True))
    return keys


def fernet_keys(purpose: str) -> list[bytes]:
    """The same keys in the form Fernet takes (url-safe base64 of 32 bytes), current first."""
    return [base64.urlsafe_b64encode(k) for k in verification_keys(purpose)]
