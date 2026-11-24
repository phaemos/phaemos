from datetime import datetime, timedelta, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db import Base

# three boots inside ten minutes is a restart loop (a brown-out or a crash on start-up)
RESET_LOOP_BOOTS = 3
RESET_LOOP_WINDOW = timedelta(minutes=10)
# boot times older than this are dropped, so the list stays short
BOOT_HISTORY_KEEP = timedelta(hours=1)


class DeviceHealth(Base):
    """The latest vitals a node reported: one row per device, replaced by each post that carries health fields."""

    __tablename__ = "device_health"

    # the device id is the key, so there is at most one row per device. Deleting the device deletes the row
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
    boot_count = Column(Integer)
    uptime_s = Column(Integer)
    reset_reason = Column(String(40))
    rssi = Column(Integer)
    heap_free = Column(Integer)
    firmware_version = Column(String(50))
    last_seq = Column(BigInteger)
    # when the node last reported any of these
    reported_at = Column(DateTime(timezone=True))
    # the latest fault map: sensor key -> state. Empty when all was well in the latest post
    faults = Column(JSONB, nullable=False, default=dict, server_default="{}")
    # posts lost to a gap in the sequence number, in total and when the latest gap was seen
    lost_posts = Column(BigInteger, nullable=False, default=0, server_default="0")
    last_gap_at = Column(DateTime(timezone=True))
    # how many health fields the node has sent that were out of bounds or malformed and so were dropped
    dropped_fields = Column(BigInteger, nullable=False, default=0, server_default="0")
    # the latest state of each serial link the hub reported: {"nano": {"ok": 1042, "crc": 0, ...}}
    links = Column(JSONB, nullable=False, default=dict, server_default="{}")
    # the hub's latest bench counters (migration 028)
    diag = Column(JSONB, nullable=False, default=dict, server_default="{}")
    # true while the firmware says its image does not match the board, with the monitoring alert it raises open
    board_mismatch = Column(Boolean, nullable=False, default=False, server_default="false")
    # the sensor keys the firmware says it was built without, as the hub last reported them. Kept apart from the admin's
    # own list on the device
    not_fitted_by_firmware = Column(JSONB, nullable=False, default=list, server_default="[]")
    # per sensor key: when its fault began, when it last came back ok and its recent state changes. The fault alerts
    # are raised and resolved from this: {"bme280": {"since": iso, "ok_since": iso, "flips": [iso]}}
    sensor_track = Column(JSONB, nullable=False, default=dict, server_default="{}")
    # ISO times of the boots seen in the last hour, newest last. The restart loop is counted from this
    boot_events = Column(JSONB, nullable=False, default=list, server_default="[]")

    def recent_boots(self, now: datetime, window: timedelta = RESET_LOOP_WINDOW) -> int:
        cutoff = now - window
        count = 0
        for stamp in self.boot_events or []:
            try:
                when = datetime.fromisoformat(stamp)
            except (TypeError, ValueError):
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when >= cutoff:
                count += 1
        return count

    def in_reset_loop(self, now: datetime | None = None) -> bool:
        return self.recent_boots(now or datetime.now(timezone.utc)) >= RESET_LOOP_BOOTS

    @property
    def reset_loop(self) -> bool:
        # read by the API response, so it is worked out at the time of the request
        return self.in_reset_loop()
