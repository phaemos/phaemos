"""The id of a request: taken from `X-Request-ID` when it is a safe short token, otherwise made."""

import re
import uuid
from contextvars import ContextVar

HEADER = "X-Request-ID"
# a fixed character set and a bounded length, so the value is safe in a log line and in a header whatever a client sent
_SAFE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def accept_or_make(offered: str | None) -> str:
    return offered if offered and _SAFE.fullmatch(offered) else uuid.uuid4().hex
