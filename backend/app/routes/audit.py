from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

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
