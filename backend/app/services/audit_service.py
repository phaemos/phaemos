# put audit logging in its own service because it is a cross-cutting concern - any route
# can call log_action() without knowing anything about how audit records are stored.
# keeping it separate also means audit logging can be silenced or redirected (e.g. swapped to
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
        db:          SQLAlchemy session, passed in rather than created here
                     so the audit insert shares the same transaction as the main operation,
                     avoiding partial writes if the caller rolls back.
        user_id:     ID (or email) of the authenticated user performing the action.
        action:      Short verb describing what happened, e.g. "create", "update", "delete".
        resource:    The entity type being acted on, e.g. "device", "ticket", "user".
        resource_id: The primary key of the specific entity, as a string for flexibility.
        detail:      Optional free-text context, e.g. changed field names and old/new values.
    """
    # use a try/except here because audit logging must never crash the main request.
    # if the audit_log table is missing or the DB is briefly unavailable, the primary
    # operation should still succeed - a lost audit row is far less damaging than a
    # failed user-facing write.
    # a request made with an access token names the token on every row it writes
    from app.services import token_access
    box = token_access.current_token.get()
    if box and box.get("id"):
        detail = f"{detail} [via token {box['id']}]".strip()
    try:
        from sqlalchemy import text  # Import here to avoid a circular dependency at module level
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
                # use timezone-aware UTC so the timestamp is unambiguous regardless
                # of where the server is deployed.
                "created_at": datetime.now(tz=timezone.utc),
            },
        )
        # commit separately here so the audit row is persisted even if the caller's
        # outer transaction is later rolled back for unrelated reasons.
        db.commit()
    except Exception as exc:  # noqa: BLE001
        # swallow the exception intentionally - see docstring above.
        # the rollback prevents a half-open transaction from blocking future queries
        # on this session.
        db.rollback()
        # log to stderr anyway so operators can detect if audit logging is broken
        # without it causing visible errors to end users. Only the kind of error is
        # printed: the message of a database error can carry the values of the row.
        import sys
        print(f"[audit_service] WARNING: failed to write audit log: {type(exc).__name__}", file=sys.stderr)
