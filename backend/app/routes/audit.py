import csv
import hashlib
import hmac
import io
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.deps import Page, set_total
from app.errors import ApiError, Code
from app.limiter import limiter, named
from app.schemas.audit import AuditEntry
from app.services import csv_safe
from app.services.telemetry_buckets import as_utc
from app.services.keys import derive_key
from app.db import get_db
from app.models.user import User
from app.routes.auth import require_admin

router = APIRouter()

# the export is built in memory
EXPORT_MAX_ROWS = 100_000


@router.get("/audit-logs", response_model=list[AuditEntry])
@limiter.limit("60/minute")
def list_audit_logs(
    request: Request,
    response: Response,
    from_: datetime | None = Query(default=None, alias="from", description="Rows at or after this time. A time with no zone is UTC"),
    to: datetime | None = Query(default=None, description="Rows at or before this time. A time with no zone is UTC"),
    action: str | None = Query(default=None),
    user_id: uuid.UUID | None = Query(default=None),
    page: Page = Depends(Page.up_to(500, default=50)),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    # use raw SQL here to stay consistent with audit_service.py which also uses
    # raw SQL for writes - keeping both sides consistent avoids having a mismatch
    # where the ORM model diverges from the raw-SQL schema the service relies on.
    where, params = _filters(from_, to, action, user_id)
    total = db.execute(text(f"SELECT count(*) FROM audit_log WHERE {where}"), params).scalar() or 0
    set_total(response, total)
    rows = db.execute(
        text(f"SELECT id, user_id, action, resource, resource_id, detail, created_at FROM audit_log WHERE {where} "
             "ORDER BY created_at DESC, id LIMIT :limit OFFSET :skip"),
        {**params, "limit": page.limit, "skip": page.offset},
    ).fetchall()
    return [AuditEntry(**{**row._mapping, "id": str(row.id)}) for row in rows]


def _filters(from_, to, action, user_id):
    # build the WHERE clause dynamically so unused filters add no overhead.
    # all parameters are passed as bound values to prevent SQL injection.
    conditions = ["1=1"]
    params: dict = {}
    if from_:
        conditions.append("created_at >= :from_ts")
        params["from_ts"] = as_utc(from_)
    if to:
        conditions.append("created_at <= :to_ts")
        params["to_ts"] = as_utc(to)
    if action:
        conditions.append("action = :action")
        params["action"] = action
    if user_id:
        conditions.append("user_id = :user_id")
        params["user_id"] = str(user_id)
    return " AND ".join(conditions), params


@router.get("/audit-logs/export", response_class=StreamingResponse)
@limiter.limit(named("sensitive"))
def export_audit_logs(
    request: Request,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    action: str | None = Query(default=None),
    user_id: uuid.UUID | None = Query(default=None),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    where, params = _filters(from_, to, action, user_id)
    rows = db.execute(
        text(
            f"""
            SELECT id, user_id, action, resource, resource_id, detail, created_at
            FROM audit_log
            WHERE {where}
            ORDER BY created_at DESC, id
            LIMIT {EXPORT_MAX_ROWS + 1}
            """
        ),
        params,
    ).fetchall()
    if len(rows) > EXPORT_MAX_ROWS:
        # the export is built in memory, so it has a ceiling. Ask for a shorter range
        raise ApiError(422, Code.INVALID_RANGE, f"An export holds at most {EXPORT_MAX_ROWS} rows. Ask for a shorter range with from and to")

    # build CSV in memory - audit logs are small enough that streaming from a
    # StringIO buffer is simpler than a true streaming generator.
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "user_id", "action", "resource", "resource_id", "detail", "created_at"])
    for row in rows:
        writer.writerow(csv_safe.safe_row([str(v) if v is not None else "" for v in row]))
    csv_bytes = buf.getvalue().encode("utf-8")

    # sign the response body with an HMAC-SHA256 so recipients can verify
    # the export has not been tampered with after leaving the server.
    sig = hmac.new(derive_key("audit_export"), csv_bytes, hashlib.sha256).hexdigest()

    filename = f"audit-export-{date.today()}.csv"
    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-HMAC-SHA256": sig,
        },
    )
