"""Response models for the small routes that answered a bare dict: the alert metrics, the assignee list, the firmware replies and the demo feed."""

from pydantic import BaseModel


class DailyLimit(BaseModel):
    limit: int
    count: int
    reached: bool
    # when the limit resets: 00:00 UTC, with a Z
    resets_at: str


class AlertMetrics(BaseModel):
    metrics: list[dict]
    conditions: list[str]
    severities: list[str]
    # where today's daily email and text limits stand. No recipient and no address
    daily_limits: dict[str, DailyLimit]


class Assignee(BaseModel):
    id: str
    name: str


class BatchFirmwareResult(BaseModel):
    queued: int
    tag: str
    target_version: str


class FirmwareMeta(BaseModel):
    version: str
    filename: str | None = None
    size: int | None = None
    checksum: str | None = None


class DemoStarted(BaseModel):
    device_id: str
    # the key of the demo machine, only when it was made by this call
    api_key: str | None = None
    status: str


class DemoStopped(BaseModel):
    status: str
