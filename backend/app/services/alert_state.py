"""
Alert state - the two helpers every path that opens a system alert shares: the per-device lock and the guarded insert.

They live apart from health_service and alert_service because both of those open system alerts and one imports the
other's neighbours. Keeping them here lets the ingest route, the liveness sweep, the sensor fault alerts and the model's
anomaly alert all use the same lock and the same refusal of a duplicate.
"""

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.alert import Alert

# the unique indexes that allow one open system alert of a kind per device and sensor and one open rule alert per machine and
# rule. The first is named uq_alerts_open_kind on a database that still has migration 020's index
OPEN_ALERT_INDEXES = frozenset({"uq_alerts_open_system", "uq_alerts_open_rule", "uq_alerts_open_kind"})
# how long any lock wait inside a post's transaction may last. A wait longer than this is a fault and the post fails
# with a lock timeout that the route retries once, so no reading is lost to a stuck lock
LOCK_TIMEOUT = "5s"


def set_lock_timeout(db: Session) -> None:
    """Bound every lock wait for the rest of this transaction (the advisory lock and the row locks alike)."""
    db.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))


def lock_device(db: Session, device_id) -> None:
    """
    Serialise the health and alert changes of one device for the rest of the transaction.

    A transaction-level advisory lock keyed on the device, taken before any state is read. It is used and not a row
    lock on device_health because that row does not exist for a node's first post (two first posts would both insert
    it) and because the alert state is spread over the devices row, device_health and the alerts themselves, which one
    row lock would not cover. It is released by the commit and a wait is bounded by the lock timeout. A second post
    from the same node waits for the first and then sees what it wrote and no reading is lost to the wait or to a key
    clash.
    """
    set_lock_timeout(db)
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"phaemos:device-state:{device_id}"},
    )


def is_open_alert_violation(exc: IntegrityError) -> bool:
    """True when an integrity error is the refusal of a second open alert and not some other constraint."""
    orig = exc.orig
    diag = getattr(orig, "diag", None)
    return getattr(orig, "pgcode", None) == "23505" and getattr(diag, "constraint_name", None) in OPEN_ALERT_INDEXES


def add_alert(db: Session, alert: Alert) -> bool:
    """
    Add a system alert, unless the database already holds an open one of its kind for the device.

    True when it was added. The unique index (migration 020) is what refuses the duplicate, so even a path that did not
    take the device lock cannot leave two open. The insert runs in a savepoint, so a refusal costs nothing else in the
    transaction and in particular never costs the reading. Only that one refusal is absorbed: a foreign key or a NOT
    NULL failure still raises, so a caller is never told an alert was raised when it was not.
    """
    try:
        with db.begin_nested():
            db.add(alert)
            db.flush()
        return True
    except IntegrityError as exc:
        if is_open_alert_violation(exc):
            return False
        raise
