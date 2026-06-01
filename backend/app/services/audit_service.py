# I put audit logging in its own service because it is a cross-cutting concern - any route
# can call log_action() without knowing anything about how audit records are stored.
# Keeping it separate also means we can silence or redirect audit logging (e.g. swap to
# an external SIEM) by editing only this file, without touching any route logic.

from sqlalchemy.orm import Session
from datetime import datetime, timezone
import uuid


def log_action(
    db: Session,
    user_id: str,
    action: str,
    resource: str,
    resource_id: str,
    detail: str = "",
) -> None:
    """Record a single audit event in the audit_log table.

    Args:
        db:          SQLAlchemy session - I pass this in rather than creating a new one
                     so the audit insert shares the same transaction as the main operation,
                     avoiding partial writes if the caller rolls back.
        user_id:     ID (or email) of the authenticated user performing the action.
        action:      Short verb describing what happened, e.g. "create", "update", "delete".
        resource:    The entity type being acted on, e.g. "device", "ticket", "user".
        resource_id: The primary key of the specific entity, as a string for flexibility.
        detail:      Optional free-text context, e.g. changed field names and old/new values.
    """
    # I use a try/except here because audit logging must never crash the main request.
    # If the audit_log table is missing or the DB is briefly unavailable, the primary
    # operation should still succeed - a lost audit row is far less damaging than a
    # failed user-facing write.
    try:
        from sqlalchemy import text  # I import here to avoid a circular dependency at module level
        db.execute(
            text("""
            INSERT INTO audit_log (id, user_id, action, resource, resource_id, detail, created_at)
            VALUES (:id, :user_id, :action, :resource, :resource_id, :detail, :created_at)
            """),
            {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "action": action,
                "resource": resource,
                "resource_id": resource_id,
                "detail": detail,
                # I use timezone-aware UTC so the timestamp is unambiguous regardless
                # of where the server is deployed.
                "created_at": datetime.now(tz=timezone.utc),
            },
        )
        # I commit separately here so the audit row is persisted even if the caller's
        # outer transaction is later rolled back for unrelated reasons.
        db.commit()
    except Exception as exc:  # noqa: BLE001
        # I swallow the exception intentionally - see docstring above.
        # The rollback prevents a half-open transaction from blocking future queries
        # on this session.
        db.rollback()
        # I still log to stderr so operators can detect if audit logging is broken
        # without it causing visible errors to end users.
        import sys
        print(f"[audit_service] WARNING: failed to write audit log: {exc}", file=sys.stderr)
