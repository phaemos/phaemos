import csv
import hashlib
import hmac
import io
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models.user import User
from app.routes.auth import require_admin

router = APIRouter()


@router.get("/audit-logs")
def list_audit_logs(
    skip: int = 0,
    limit: int = 50,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    # I use raw SQL here to stay consistent with audit_service.py which also uses
    # raw SQL for writes - keeping both sides consistent avoids having a mismatch
    # where the ORM model diverges from the raw-SQL schema the service relies on.
    rows = db.execute(
        text(
            """
            SELECT id, user_id, action, resource, resource_id, detail, created_at
            FROM audit_log
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :skip
            """
        ),
        {"limit": limit, "skip": skip},
    ).fetchall()

    # I convert Row objects to dicts so FastAPI can serialise them as JSON without
    # needing a Pydantic model for the audit log table.
    return [dict(row._mapping) for row in rows]


@router.get("/audit-logs/export")
def export_audit_logs(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    action: str | None = Query(default=None),
    user_id: uuid.UUID | None = Query(default=None),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    # I build the WHERE clause dynamically so unused filters add no overhead.
    # All parameters are passed as bound values to prevent SQL injection.
    conditions = ["1=1"]
    params: dict = {}
    if from_:
        conditions.append("created_at >= :from_ts")
        params["from_ts"] = from_
    if to:
        conditions.append("created_at <= :to_ts")
        params["to_ts"] = to
    if action:
        conditions.append("action = :action")
        params["action"] = action
    if user_id:
        conditions.append("user_id = :user_id")
        params["user_id"] = str(user_id)

    rows = db.execute(
        text(
            f"""
            SELECT id, user_id, action, resource, resource_id, detail, created_at
            FROM audit_log
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC
            """
        ),
        params,
    ).fetchall()

    # Build CSV in memory - audit logs are small enough that streaming from a
    # StringIO buffer is simpler than a true streaming generator.
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "user_id", "action", "resource", "resource_id", "detail", "created_at"])
    for row in rows:
        writer.writerow([str(v) if v is not None else "" for v in row])
    csv_bytes = buf.getvalue().encode("utf-8")

    # I sign the response body with an HMAC-SHA256 so recipients can verify
    # the export has not been tampered with after leaving the server.
    sig = hmac.new(settings.secret_key.encode(), csv_bytes, hashlib.sha256).hexdigest()

    filename = f"audit-export-{date.today()}.csv"
    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-HMAC-SHA256": sig,
        },
    )
