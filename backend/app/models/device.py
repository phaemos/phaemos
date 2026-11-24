import uuid
# column and the type classes (String, DateTime, etc.) describe the shape of each DB column
from sqlalchemy import BigInteger, Boolean, Column, ForeignKey, Index, Integer, String, DateTime, func, text
from sqlalchemy.orm import relationship
# UUID is imported from the PostgreSQL dialect because it's a Postgres-specific column type
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from app.db import Base


# inheriting from Base registers this class with SQLAlchemy's ORM metadata
class Device(Base):
    # __tablename__ tells SQLAlchemy which database table this class maps to
    __tablename__ = "devices"

    # UUID(as_uuid=True) makes SQLAlchemy return Python uuid.UUID objects instead of raw strings
    # default=uuid.uuid4 means a new UUID is generated in Python before the row is inserted
    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # nullable=False enforces a NOT NULL constraint at the database level
    name       = Column(String(100), nullable=False)
    # no nullable=False means this column is optional - the device may not have a location yet
    location   = Column(String(100))
    type       = Column(String(50))          # esp32 / arduino / stm32
    # the API key is never stored (migration 031). key_id is its first 8 characters in clear, to find the machine and
    # key_hash is a keyed hash of the whole key (services/device_keys.py). The old clear column stays only so a database
    # from before the migration can be upgraded: it is null once its key is hashed
    key_id     = Column(String(16), nullable=True)
    key_hash   = Column(String(64), nullable=True)
    legacy_api_key = Column("api_key", String(255), unique=True, nullable=True)
    status            = Column(String(20), default="offline")  # online/offline/warning/fault
    firmware_version  = Column(String(50))   # set when device downloads or reports its OTA version
    # timezone=True stores the timestamp as UTC in the DB, preventing timezone confusion
    last_seen  = Column(DateTime(timezone=True))
    # server_default=func.now() lets the database set the timestamp, which is more reliable
    # than relying on application-side time (avoids clock-skew issues between app and DB servers)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # keep owner_id nullable so existing unowned devices are valid and technicians
    # can see them (unowned = shared/unassigned, not hidden).
    owner_id   = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # use a PostgreSQL ARRAY column rather than a join table because the tag set is
    # small and querying with `tag = ANY(tags)` is fast with a GIN index at this scale.
    tags       = Column(ARRAY(String), server_default="{}", nullable=False)
    # how often the node posts, in seconds. The liveness sweep judges silence in multiples of it
    expected_interval_s = Column(Integer, nullable=False, default=5, server_default="5")
    # online / late / offline, from the age of the last post. A post sets it to online at once and the sweep
    # moves it on. status stays the older two-state word: see services/liveness_service.py
    link_state = Column(String(10), nullable=False, default="offline", server_default="offline")

    # sensor keys that are not expected on this machine (an admin sets them). A fault reported for one raises no
    # alert and is shown as "not fitted"
    not_fitted = Column(ARRAY(String), server_default="{}", nullable=False)
    # since when the node has posted without any scored reading and which model inputs its readings lacked;
    # both are empty while readings are scored. The no-scored-reading alert is raised from them
    unscored_since = Column(DateTime(timezone=True))
    unscored_missing = Column(ARRAY(String), server_default="{}", nullable=False)
    # true while the no-scored-reading alert is open, so a steady state costs no query per post
    unscored_alerted = Column(Boolean, nullable=False, default=False, server_default="false")
    # when the vibration node last said a sample hit the sensor's limit and whether the clipping alert is open
    # (migration 021). The alert resolves after a minute without it
    clipping_last_true = Column(DateTime(timezone=True))
    clipping_alerted = Column(Boolean, nullable=False, default=False, server_default="false")

    # replay protection (migration 031). The pair (boot, seq) of the last post accepted. replay_protected turns true the first
    # time the machine sends the pair and from then on every post must carry a newer one. An older firmware never sends it
    # and is shown as having no protection
    last_boot = Column(BigInteger, nullable=True)
    last_seq = Column(BigInteger, nullable=True)
    replay_protected = Column(Boolean, nullable=False, default=False, server_default="false")
    # posts refused for an old pair since the last accepted one and when the latest was. An admin accepts a new counter when
    # a hub's flash was wiped
    replay_refused = Column(Integer, nullable=False, default=0, server_default="0")
    replay_refused_at = Column(DateTime(timezone=True), nullable=True)
    # when the counter last rose by more than a restart or lost posts explain and what it did. Shown as a warning on the machine's
    # health. Cleared when an admin accepts a new counter
    counter_jump_at = Column(DateTime(timezone=True), nullable=True)
    counter_jump_note = Column(String(120), nullable=True)
    # per continuous sensor column: the last value, since when it has not changed and how much it moved before (stuck sensor
    # check, services/stuck_sensors.py)
    stuck_state = Column(JSONB, nullable=False, default=dict, server_default="{}")
    # the anomaly model's change detector state for this machine (migration 039): about 1 kB of accumulators that must survive
    # between readings and be shared by every worker. Read and written under the device lock a post already holds
    # (services/detector_store.py). Null means a fresh detector
    detector_state = Column(JSONB, nullable=True)
    # another node in the same place whose air temperature is this machine's ambient reference (migration 041). The anomaly
    # model judges this machine's temperatures as their rise above that reading, so a warmer room is not a fault. Null: none
    ambient_source_id = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (Index("uq_devices_key_id", "key_id", unique=True, postgresql_where=text("key_id IS NOT NULL")),)

    @property
    def api_key(self):
        """The plain key, known only on the instance that just made it. It is not stored and a loaded row has none."""
        return self.__dict__.get("_plain_key")

    @api_key.setter
    def api_key(self, value):
        from app.services import device_keys

        self.__dict__["_plain_key"] = value
        device_keys.store(self, value)

    # read-only link so a reply can name the owner without an extra query per machine;
    # only the name is exposed, because most roles cannot list users.
    owner = relationship("User", foreign_keys=[owner_id], viewonly=True, lazy="joined")

    @property
    def owner_name(self) -> str | None:
        return self.owner.name if self.owner else None
