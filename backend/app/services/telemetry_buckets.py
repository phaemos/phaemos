# time-bucketed telemetry for long chart ranges.
# a node posts every 5 seconds, so a week is about 120,000 rows. averaging in SQL keeps that
# off the wire and out of Python: the database returns one row per bucket.
import math
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, Interval, case, func, literal, text
from sqlalchemy.dialects.postgresql import aggregate_order_by, array_agg
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models.telemetry import Telemetry

MIN_BUCKET_SECONDS = 10
MAX_BUCKET_SECONDS = 86_400
# well above the 400 or so points a chart can draw legibly and about a week of 10 minute buckets
MAX_BUCKETS = 1_000
# the longest window one bucketed request may aggregate. The bucket cap limits rows returned but not rows read:
# with one day buckets a window could otherwise span years of readings. 31 days covers the dashboard's 7 day
# range with room to spare
MAX_WINDOW = timedelta(days=31)
# a bucketed query that runs longer than this is cancelled by the database and answered with 503
STATEMENT_TIMEOUT_MS = 5_000


class BucketQueryTimeout(Exception):
    pass

# buckets align to the Unix epoch rather than to from_ts, so the same instant always falls
# in the same bucket and a sliding window does not reshuffle the points on every refresh
_ORIGIN = literal(datetime(1970, 1, 1, tzinfo=timezone.utc), type_=DateTime(timezone=True))

# the aggregate for each column, chosen by what the reading means:
# - mean for continuous readings, where the typical level is what a long chart should show
# - circular mean for shaft_angle, which wraps at 360 degrees: readings of 359 and 1 average to 0, not 180
# - mean and also a peak (largest absolute value) for the signed axes, because their mean is the static offset
#   and hides the vibration the chart exists to show
# - maximum for the anomaly score and vibration magnitude, where a short spike is what an average would hide
# - the FFT frequency of the reading with the strongest vibration, since the highest frequency in the bucket
#   is not the frequency of the strongest vibration
# - logical OR for flags, so one raised alarm marks the whole bucket
MEAN_COLUMNS = (
    "temperature", "humidity", "pressure",
    "vibration_x", "vibration_y", "vibration_z",
    "gyro_x", "gyro_y", "gyro_z",
    "bus_voltage", "current_ma", "power_mw",
    "ir_temperature", "distance_mm",
    "gas_level", "shaft_rpm",
    "sound_level", "light_level", "contact_temp", "moisture_level",
    # the Black Pill's RMS and axis means and the Nano's values
    "vib_rms_x", "vib_rms_y", "vib_rms_z", "stm32_vib_x", "stm32_vib_y", "stm32_vib_z",
    "nano_temp", "nano_hum", "nano_pres", "nano_light", "nano_moist",
)
# vib_peak is itself a largest value, so the bucket keeps the largest of them
# a bucket whose shaft angles agree less than this (the length of their mean vector, 0 to 1) has no meaningful mean angle
MIN_ANGLE_AGREEMENT = 0.1
MAX_COLUMNS = ("anomaly_score", "vib_magnitude", "vib_peak")
SIGNED_AXES = (
    "vibration_x", "vibration_y", "vibration_z", "gyro_x", "gyro_y", "gyro_z",
    "stm32_vib_x", "stm32_vib_y", "stm32_vib_z",
)
OR_COLUMNS = ("gas_alert", "water_detected", "nano_water", "vib_clipping", "is_anomaly")


def window_span(from_ts: datetime, to_ts: datetime | None) -> timedelta:
    # a timestamp without a zone is read as UTC, as everywhere else in the route
    end = as_utc(to_ts) if to_ts else datetime.now(timezone.utc)
    return end - as_utc(from_ts)


def bucket_count(from_ts: datetime, to_ts: datetime, bucket: int) -> int:
    # most buckets the window can touch. alignment to the epoch can add one partial bucket
    span = (to_ts - from_ts).total_seconds()
    return max(0, math.ceil(span / bucket)) + 1


def as_utc(ts: datetime) -> datetime:
    # a timestamp without a zone is read as UTC
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def window_bucket_count(from_ts: datetime, to_ts: datetime | None, bucket: int) -> int:
    end = as_utc(to_ts) if to_ts else datetime.now(timezone.utc)
    return bucket_count(as_utc(from_ts), end, bucket)


def bucketed_telemetry(
    db: Session,
    device_id: uuid.UUID,
    bucket: int,
    from_ts: datetime,
    to_ts: datetime | None,
    node_type: str | None,
) -> list[dict]:
    # one dict per bucket that holds at least one reading, newest first.
    # the filter is on device_id and recorded_at only, the same predicate the raw route uses, so
    # an index on those two columns serves both. empty buckets never appear because GROUP BY only
    # sees buckets that have rows.
    start = func.date_bin(literal(timedelta(seconds=bucket), type_=Interval), Telemetry.recorded_at, _ORIGIN).label("bucket_start")

    cols = [start, func.count().label("reading_count")]
    cols += [func.avg(getattr(Telemetry, c)).label(c) for c in MEAN_COLUMNS]
    cols += [func.max(getattr(Telemetry, c)).label(c) for c in MAX_COLUMNS]
    cols += [func.bool_or(getattr(Telemetry, c)).label(c) for c in OR_COLUMNS]
    cols += [func.max(func.abs(getattr(Telemetry, c))).label(f"{c}_peak") for c in SIGNED_AXES]
    # circular mean in degrees. atan2d returns -180 to 180, so negative results are moved up by 360 and a result that
    # rounds up to exactly 360 is brought back to 0, so the answer is always 0 up to but not including 360;
    # the mean vector's length says how much the angles agree: near 0 for a shaft that is turning (the angles spread
    # all round the circle), where the mean angle is noise. Under 0.1 the bucket has no angle and the answer is null
    sin_mean = func.avg(func.sind(Telemetry.shaft_angle))
    cos_mean = func.avg(func.cosd(Telemetry.shaft_angle))
    angle = func.atan2d(sin_mean, cos_mean)
    upward = case((angle < 0, angle + 360), else_=angle)
    wrapped = case((upward >= 360, upward - 360), else_=upward)
    length = func.sqrt(func.power(sin_mean, 2) + func.power(cos_mean, 2))
    cols.append(case((length < MIN_ANGLE_AGREEMENT, None), else_=wrapped).label("shaft_angle"))
    # the frequency of the strongest vibration in the bucket. Rows with no frequency sort last so a gap in
    # one column never hides a frequency that another reading carried
    strongest = array_agg(aggregate_order_by(Telemetry.fft_peak_hz, Telemetry.fft_peak_hz.is_(None), Telemetry.vib_magnitude.desc().nulls_last()))
    cols.append(strongest[1].label("fft_peak_hz"))

    # zone-less bounds are made UTC here so the answer does not depend on the database's own time zone
    q = db.query(*cols).filter(Telemetry.device_id == device_id, Telemetry.recorded_at >= as_utc(from_ts))
    if to_ts:
        q = q.filter(Telemetry.recorded_at <= as_utc(to_ts))
    if node_type:
        q = q.filter(Telemetry.node_type == node_type)
    # SET LOCAL lasts only until this transaction ends. The session is closed (rolled back) at the end of the
    # request, so the limit cannot reach another request on the pooled connection
    db.execute(text(f"SET LOCAL statement_timeout = {int(STATEMENT_TIMEOUT_MS)}"))
    try:
        rows = q.group_by(start).order_by(start.desc()).all()
    except OperationalError as exc:
        # 57014 is query_canceled, which is what the statement timeout raises
        if getattr(exc.orig, "pgcode", None) == "57014":
            raise BucketQueryTimeout from exc
        raise

    out = []
    for row in rows:
        item = row._asdict()
        item["recorded_at"] = item.pop("bucket_start")
        item["device_id"] = device_id
        # a bucket whose readings all lack the flag has no answer so the schema says false
        item["is_anomaly"] = bool(item["is_anomaly"])
        out.append(item)
    return out
