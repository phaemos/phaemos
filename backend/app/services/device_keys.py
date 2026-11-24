"""
Device API keys: how they are made, stored and checked.

A key is 43 random URL-safe characters (256 bits). The database keeps two things about it and never the key:
  key_id    the first KEY_ID_LENGTH characters, stored in clear. It is how a post finds its machine without scanning every
            row. It is not a secret on its own: it leaves 208 unknown bits
  key_hash  HMAC-SHA256 of the whole key, keyed with services/keys.py derive_key("device_key"): the one helper that derives
            every key from SECRET_KEY

Why a fast keyed hash and not a slow password hash (bcrypt, argon2): a slow hash exists to make guessing a weak, human
chosen secret expensive. A 256-bit random key cannot be guessed whatever the hash costs, so the slowness would buy nothing.
Every post of every machine (up to 60 a minute each) would pay it, which would hand an attacker who only has to send wrong
keys a cheap way to burn the server's processor. The secret in the HMAC means a copy of the database alone cannot even be used
to test a guess. A plain unsalted hash of a key would also be the same string for the same key everywhere.

An unknown key and a wrong key go through the same steps (one query, one HMAC, one constant-time compare against a stand-in
when there is no row) and give the same answer, so the time taken does not say which key ids exist.

When SECRET_KEY is rotated the hashes stay valid. A key is checked under the current derived key and, while SECRET_KEY_PREVIOUS
is set, under the previous one too (always both, so the cost does not depend on which one matches). A machine that matches only
the previous one is re-hashed under the current key on that very post, so no machine is locked out and each one moves over by
itself. Drop SECRET_KEY_PREVIOUS only after every machine has posted since the rotation (a machine that has not would need its
key rotated by an admin).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.services.keys import derive_key

logger = logging.getLogger(__name__)

KEY_ID_LENGTH = 8
# the longest header value that is checked at all. A key is 43 characters (older ones up to 36)
MAX_KEY_LENGTH = 200


def hash_key(key: str, previous: bool = False) -> str:
    return hmac.new(derive_key("device_key", previous=previous), key.encode("utf-8"), hashlib.sha256).hexdigest()


def key_id_of(key: str) -> str:
    return key[:KEY_ID_LENGTH]


def new_key() -> str:
    return secrets.token_urlsafe(32)


def store(device, key: str) -> None:
    """Set a device's identifiers from a plain key. The plain key is not stored: only the id and the hash are."""
    device.key_id = key_id_of(key)
    device.key_hash = hash_key(key)
    device.legacy_api_key = None


def _dummy_hash() -> str:
    """What an unknown key id is compared against. Worked out each time from a fixed text so it costs nothing to look up."""
    return hmac.new(derive_key("device_key"), b"no such key", hashlib.sha256).hexdigest()


def find_device(db: Session, presented: str):
    """
    The device a presented key belongs to. None when there is none.

    Costs the same whether the key id is unknown, the key is wrong or it is right. A hash made under the previous server key
    is accepted while SECRET_KEY_PREVIOUS is set and the machine is re-hashed under the current key on the spot. A machine
    still holding its key in clear (a database from before migration 031 that the start-up upgrade has not reached) is checked
    against that and upgraded the same way.
    """
    from app.models.device import Device

    presented = presented if isinstance(presented, str) else ""
    usable = 0 < len(presented) <= MAX_KEY_LENGTH
    candidate = presented if usable else "x" * KEY_ID_LENGTH
    device = db.query(Device).filter(Device.key_id == key_id_of(candidate)).first() if usable else None
    expected = (device.key_hash if device is not None and device.key_hash else None) or _dummy_hash()
    # every key in use is tried, the previous one only while it is set. None is skipped once one has matched
    tries = [hash_key(candidate)]
    if settings.secret_key_previous:
        tries.append(hash_key(candidate, previous=True))
    matches = [hmac.compare_digest(h, expected) for h in tries]
    ok = any(matches) and device is not None and device.key_hash is not None and usable
    if ok and not matches[0]:
        # valid under the previous server key only: moved to the current one
        store(device, presented)
        db.commit()
    if device is not None and device.key_hash is None and device.legacy_api_key is not None and usable:
        # the old plain key: compared in constant time, then hashed and removed
        if hmac.compare_digest(device.legacy_api_key.encode("utf-8"), presented.encode("utf-8")):
            store(device, presented)
            db.commit()
            return device
    return device if ok else None


def device_for_key(db: Session, presented: str):
    """The device a key belongs to or a 401 `device_key_invalid` with the same answer and cost for an unknown and a wrong key."""
    from app.errors import ApiError, Code

    device = find_device(db, presented)
    if not device:
        raise ApiError(401, Code.DEVICE_KEY_INVALID, "Invalid API key")
    return device


def upgrade_legacy_keys(db: Session) -> int:
    """
    Hash every key still held in clear and remove the clear copy. Safe to run twice and from several workers at once.

    The hash needs the server's secret key, which is why this runs in the application and not in the SQL file: migration
    031 adds the columns and the key ids and this fills in the hashes when the application starts.
    """
    from app.models.device import Device

    # one worker at a time. The lock is released by the commit
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('phaemos-device-key-upgrade', 0))"))
    rows = db.query(Device).filter(Device.key_hash.is_(None), Device.legacy_api_key.isnot(None)).all()
    for device in rows:
        store(device, device.legacy_api_key)
    db.commit()
    if rows:
        logger.info("%d device keys are now stored as hashes", len(rows))
    return len(rows)
