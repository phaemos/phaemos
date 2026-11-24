"""
Keyset paging: "the rows before this one" for lists that grow without bound.

Offset paging reads and throws away every row before the page and repeats or skips rows when new ones arrive during the walk.
A keyset cursor `before=<time>,<id>` asks for the rows that sort after that row in the list's own order (newest first, ties
broken by id), which an index answers directly however deep the page is. A page that is full carries the cursor of its last row in
`X-Next-Before`. A client walks a list by sending that back as `before` until a page comes back short.
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import Response

from app.errors import ApiError, Code


def encode(when: datetime, row_id) -> str:
    when = when if when.tzinfo is not None else when.replace(tzinfo=timezone.utc)
    return f"{when.astimezone(timezone.utc).isoformat()},{row_id}"


def decode(before: str) -> tuple[datetime, UUID]:
    """The (time, id) of a cursor. A malformed cursor is a 422 that says what one looks like."""
    try:
        stamp, row_id = before.rsplit(",", 1)
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return when, UUID(row_id)
    except (ValueError, AttributeError):
        raise ApiError(
            422, Code.INVALID_FILTER, "before must be a cursor as the API sent it in X-Next-Before: <ISO time>,<id>",
        ) from None


def set_next(response: Response, rows: list, limit: int, time_attr: str) -> None:
    """Put the cursor of the last row in X-Next-Before when the page is full, so the client knows there may be more."""
    if rows and len(rows) >= limit:
        last = rows[-1]
        response.headers["X-Next-Before"] = encode(getattr(last, time_attr), last.id)
