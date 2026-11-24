import csv
import io
import logging
import uuid
from datetime import datetime, timedelta, timezone

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import null, tuple_
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Page
from app.errors import ApiError, Code
from app.limiter import limiter
from app.models.device import Device
from app.models.telemetry import Telemetry
from app.models.user import User
from app.routes.auth import get_current_user
from app.schemas.telemetry import TelemetryBucketResponse, TelemetryIngest, TelemetryResponse
from app.services.ml_service import score_reading
from app.services.alert_service import evaluate_anomaly, evaluate_rules
from app.services import csv_safe, detector_store, keyset, replay, device_keys, alert_service, alert_state, health_service, ingest_limit, liveness_service, ml_service, ws_manager
from app.services.sensor_map import BOOLEAN_FIELDS
from app.services.access import get_device_for_read
from app.services.heavy_reads import heavy_read
from app.services.telemetry_buckets import (
    MAX_BUCKET_SECONDS,
    MAX_BUCKETS,
    MAX_WINDOW,
    MIN_BUCKET_SECONDS,
    BucketQueryTimeout,
    as_utc,
    bucketed_telemetry,
    window_bucket_count,
    window_span,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# the anomaly change detector keeps its state in the database, shared by every worker
ml_service.set_state_store(detector_store.DbStateStore(ml_service.state_store()))

# the most raw rows one history request may ask for. The dashboard asks for at most 1500
MAX_LIMIT = 5000
# the longest span one CSV export may cover, so a single request cannot read a machine's whole history
EXPORT_MAX_SPAN = timedelta(days=31)
EXPORT_BATCH = 1000
# the dashboard polls these routes every 5 seconds from a handful of components: about 12 requests a minute each
# on a machine page, around 50 in total on the busiest page. 600 a minute per address is a dozen times that and
# still stops a runaway loop or a scraper
READ_LIMIT = "600/minute"


def get_device_by_api_key(api_key: str, db: Session) -> Device:
    # the device API key is the auth mechanism for firmware requests. Only a hash of it is stored, so the lookup is by the
    # key's public id and the hash is compared in constant time (services/device_keys.py). An unknown key and a wrong one
    # cost the same and answer the same
    return device_keys.device_for_key(db, api_key)


# database errors that a post can simply be run again after: a deadlock, a serialisation failure and a lock timeout
_RETRYABLE_SQLSTATES = {"40P01", "40001", "55P03"}
# failures after the commit already logged, so each kind of failure is logged once and not once per post
_logged_after_commit: set[tuple[str, str]] = set()


def _log_after_commit(kind: str, exc: Exception) -> None:
    key = (kind, type(exc).__name__)
    if key not in _logged_after_commit:
        _logged_after_commit.add(key)
        logger.error(
            "%s failed after the reading was stored (%s). The reading and the notifications already queued are kept",
            kind, type(exc).__name__,
        )


# -- observed_at: when a reading was taken, for a gateway that spooled it ------------------------------------------------
# recorded_at is the time the server RECEIVED the reading. A gateway that holds readings through an outage (the edge gateway spools
# for up to 7 days) may send observed_at with each one: the moment it was taken. It is honoured within these bounds and for these
# things only:
#   - in the past by at most OBSERVED_MAX_AGE (the spool's own limit). An older one is refused: stored as current it would be judged as
#     live and stored with its own time it is outside what any gateway keeps
#   - never in the future. One up to OBSERVED_FUTURE_SLACK ahead is a clock a little fast and is read as "now". A later one is not
#     believed: it is ignored, the reading is stored at the time it was received and quality says so
#   - it sets recorded_at, so it decides ordering, charts, exports and the history window. It never decides whether a reading is
#     current. A reading older than max(30 s, 3 intervals) is a BACKLOG reading: stored and charted at its own time and nothing
#     more. No rule, anomaly window, alert, notification or live broadcast judges it, it is not scored and it does not move the
#     machine's last_seen or link state. The device's own clock (`ts`) is stored as device_ts for display and for spotting a node
#     whose clock is wrong. It is never used for ordering or for any of the above
OBSERVED_MAX_AGE = timedelta(days=7)
OBSERVED_FUTURE_SLACK = timedelta(seconds=60)
LIVE_MIN_SECONDS = 30
LIVE_INTERVALS = 3


class ObservedRefused(Exception):
    code = Code.OBSERVED_AT_TOO_OLD
    detail = "observed_at is more than 7 days in the past. A gateway keeps readings for 7 days at most, so this one is not stored"


def resolve_observed(observed_at: datetime | None, now: datetime, interval_s: float) -> tuple[datetime, bool, str | None]:
    """(recorded_at, backlog, ignored_reason). Raises ObservedRefused for a time older than the bound."""
    if observed_at is None:
        return now, False, None
    at = observed_at if observed_at.tzinfo is not None else observed_at.replace(tzinfo=timezone.utc)
    at = at.astimezone(timezone.utc)
    if at > now + OBSERVED_FUTURE_SLACK:
        return now, False, "future"
    if at > now:
        at = now
    if now - at > OBSERVED_MAX_AGE:
        raise ObservedRefused()
    live_window = timedelta(seconds=max(LIVE_MIN_SECONDS, LIVE_INTERVALS * max(1.0, float(interval_s or 5))))
    return at, (now - at) > live_window, None


def _lock_device(db: Session, device_id) -> Device:
    """
    The device row, then its advisory lock, in the one order used everywhere.

    The device row first (the liveness sweep takes the same row first), then the device's advisory lock. A post and the sweep can
    then never wait on each other's second lock. Reading the device again under its lock also ends the stale read of its state
    that the API-key lookup left.
    """
    alert_state.set_lock_timeout(db)
    device = (
        db.query(Device)
        .filter(Device.id == device_id)
        .populate_existing()
        .with_for_update(key_share=True, of=Device)
        .one()
    )
    # every health and alert change for this device waits for the one before it, so two posts at once cannot open the
    # same alert twice or both insert the health row. Released by the commit
    health_service.lock_device(db, device.id)
    return device


def _judge(device: Device, payload: TelemetryIngest, now: datetime):
    """
    The replay rule and the observed_at rule for one reading, under the device lock. Returns (refusal, resolved).

    refusal is None or (kind, code, detail, http_status). kind is "duplicate" or "refused". Nothing is stored here except the
    refusal count and the pair is recorded as accepted only by the caller once the reading is going to be stored.
    """
    verdict = replay.judge(device, payload.boot, payload.seq)
    if verdict == replay.DUPLICATE:
        return ("duplicate", "duplicate", "this boot and seq were already accepted", 200), None
    if verdict != replay.ACCEPT:
        replay.record_refusal(device, now)
        status = 422 if verdict == replay.CEILING else 409
        code = {
            replay.OLD: Code.REPLAY_STALE, replay.MISSING: Code.REPLAY_PAIR_MISSING, replay.CEILING: Code.COUNTER_OUT_OF_RANGE,
        }[verdict]
        return ("refused", code, replay.REFUSAL_TEXT[verdict], status), None
    try:
        resolved = resolve_observed(payload.observed_at, now, device.expected_interval_s or 5)
    except ObservedRefused as exc:
        return ("refused", exc.code, exc.detail, 422), None
    return None, resolved


def _build_item(db: Session, device: Device, payload: TelemetryIngest, now: datetime, resolved) -> dict:
    """
    Everything one reading writes, except the commit. The caller holds the device lock and has judged the reading.

    A live reading is a heartbeat and runs the whole path (scoring, health, faults, stuck sensors, clipping, liveness). A backlog
    reading (see resolve_observed) is stored at its own time and that is all: it is not scored, it does not touch the health row,
    the fault alerts or the machine's last_seen and link state and nothing is queued for the rules, the anomaly window or the
    notifications.
    """
    recorded_at, backlog, ignored = resolved
    replay.record_accept(device, payload.boot, payload.seq, now)

    # the sensor readings alone: the node's health fields are kept apart, so they never reach a rule or the model;
    # a sensor the node names in `faults` is stopped here: its fields become null, so no rule fires on them and
    # the model does not score a row that lacks them. The value the node sent is kept in `quality`.
    # a claimed fault stops its sensor only while an alert for it is open (or an admin marked the sensor not fitted). A claim with no
    # alert behind it stops nothing, so it cannot be used to switch a rule off unseen. A backlog reading stops nothing at all: the
    # alerts now say nothing about the sensor's state then
    if backlog:
        allowed: set | None = set()
    else:
        allowed = health_service.stoppable_sensors(db, device) if payload.faults else set()
    reading, quality, stopped = health_service.apply_faults(payload.reading(), payload.faults, allowed)
    server: dict = {}
    previous_server: dict = {}
    if not backlog:
        # what the server finds for itself (a value outside what the part can measure, a value that stopped moving). A sensor the
        # node did not name is added to the row's fault map, so the row is marked as suspect and training leaves it out
        previous_server = dict((device.stuck_state or {}).get("_faults") or {})
        server = health_service.server_faults(db, device, payload, reading, now)
        unnamed = {k: v for k, v in server.items() if k not in ((quality or {}).get("faults") or {})}
        if unnamed:
            quality = {**(quality or {}), "faults": {**((quality or {}).get("faults") or {}), **unnamed}}
    else:
        # an impossible value in a backlog reading is still dropped (payload.dropped_values) and noted. The sensor alerts judge
        # the machine as it is now, so none is raised for it
        quality = {**(quality or {}), "backlog": True, "received_at": now.isoformat()}
    if ignored:
        quality = {**(quality or {}), "observed_at_ignored": ignored}
    # a health field that was not usable was dropped and the reading kept. Say which, so the row explains itself
    if payload.dropped_health:
        quality = {**(quality or {}), "dropped_health": list(payload.dropped_health)}
    # the same for a satellite value that was outside what its part can measure
    if payload.dropped_values:
        quality = {**(quality or {}), "dropped_values": list(payload.dropped_values)}

    # score first so the row stores both the reading and model decision atomically. A model that cannot be loaded or
    # used leaves the reading unscored with the reason in quality. It never costs the reading. A backlog reading is not scored:
    # the anomaly window must hold only readings that describe the machine now
    if backlog:
        anomaly_score, is_anomaly = None, False
    else:
        # the change detector reads and writes its state on this locked device row (services/detector_store.py), at the reading's time
        with detector_store.use(db):
            anomaly_score, is_anomaly = score_reading(reading, device_id=device.id, at=recorded_at)
        if anomaly_score is None and ml_service.scoring_problem():
            quality = {**(quality or {}), "scoring_error": ml_service.scoring_problem()}
        # say so when the general model scored a node type that has a model of its own, which could not
        if anomaly_score is not None and ml_service.used_general_fallback(reading):
            quality = {**(quality or {}), "scored_by": "general"}

    # a stopped flag is written as a real NULL, because a plain None would let the column default turn it into false
    columns = {k: (null() if k in stopped and k in BOOLEAN_FIELDS else v) for k, v in reading.items()}
    row = Telemetry(
        device_id=device.id,
        anomaly_score=anomaly_score,
        is_anomaly=is_anomaly,
        # stamped here rather than by the database's now(), which is fixed for a whole transaction, so every reading orders
        # correctly when the latest few are compared. It is the time received or the time observed that resolve_observed allowed
        recorded_at=recorded_at,
        seq=payload.seq,
        device_ts=datetime.fromtimestamp(payload.ts, tz=timezone.utc) if payload.ts is not None else None,
        quality=quality,
        **columns,
    )
    db.add(row)

    if backlog:
        # a backlog reading proves the machine was posting then and nothing about now: last_seen only moves forward to that time
        seen = device.last_seen
        if seen is None or seen < recorded_at:
            device.last_seen = recorded_at
        return {"row": row, "backlog": True, "notices": [], "clipping": None, "rule_reading": None}

    # a post is a heartbeat: the node is online from this moment, without waiting for the sweep
    was_link = device.link_state
    previously_seen = device.last_seen
    device.last_seen = now
    device.status = "online"
    device.link_state = "online"

    health = health_service.record_health(db, device, payload, now, server)
    health_service.track_server_faults(db, device, server, previous_server, now, health)
    notices: list[tuple[str, str]] = list(health.notify)
    # a node that posts but is never scored for ten minutes raises one monitoring alert. When a fault in this post
    # stopped every missing input, the sensor alert already says so
    unscored = health_service.track_scoring(
        db, device, reading, anomaly_score is not None, now, covered=stopped, node_type=payload.node_type,
    )
    if unscored:
        notices.append(unscored)
    # a sample at the vibration sensor's limit holds one machine warning open while it lasts
    clipping = health_service.track_clipping(db, device, reading, now)
    # a node that was silent has come back: close its silent-node alert and record how long it was gone
    if was_link != "online":
        liveness_service.resolve_offline_alert(db, device, previously_seen, now)
    if health.reset_loop:
        message = health_service.open_reset_loop_alert(db, device)
        if message:
            notices.append(("reset-loop", message))
    return {
        "row": row, "backlog": False, "notices": notices, "clipping": clipping,
        # the rules read the reading and the score the model gave it, so a rule on anomaly_score can fire
        "rule_reading": {**reading, "anomaly_score": anomaly_score},
    }


def _store_reading(db: Session, device_id, payload: TelemetryIngest) -> dict:
    """Everything a post writes, in one transaction, ending in the commit. Safe to run again after a rollback."""
    device = _lock_device(db, device_id)
    now = datetime.now(timezone.utc)
    # replay: judged under the device lock so two posts at once cannot both pass. A refused or repeated post stores nothing and
    # does not count as a heartbeat, so a captured post cannot keep a silent machine looking online
    refusal, resolved = _judge(device, payload, now)
    if refusal is not None:
        db.commit()
        return {"refusal": refusal}
    item = _build_item(db, device, payload, now, resolved)
    db.commit()
    db.refresh(item["row"])
    # the reply is built here, while the session is open, as plain values. The session is closed as this function
    # returns, so nothing after it may read the row
    return {
        "device": device,
        "reply": TelemetryResponse.model_validate(item["row"]),
        "backlog": item["backlog"],
        "rule_reading": item["rule_reading"],
        "notices": item["notices"],
        "clipping": item["clipping"],
    }


def _after_commit(db: Session, background_tasks, device: Device, stored: dict) -> None:
    """The steps after the commit for one stored LIVE reading. Nothing here may turn the reply into an error."""

    def guarded(kind: str, fn, *args) -> None:
        # the reading is stored. Nothing after the commit may turn the reply into an error or drop the notifications that
        # are already queued: a failure is logged once for its kind and the next step still runs
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001
            _log_after_commit(kind, exc)
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass

    # the alerts written before the commit have their emails queued now, as background tasks
    def queue_notices() -> None:
        for kind, message in stored["notices"]:
            alert_service.notify_monitoring(background_tasks, device, kind, message)
        if stored["clipping"]:
            alert_service.notify_machine_warning(background_tasks, device, "vib_clipping", stored["clipping"])

    guarded("queueing the monitoring notifications", queue_notices)
    # alert rules read the committed state. Email, SMS, Discord and webhooks go out through the notify pool
    guarded("evaluating the alert rules", evaluate_rules, device, stored["rule_reading"], db, background_tasks)
    # the model's own alert, raised only when a run of readings stays anomalous
    guarded("evaluating the model's anomaly alert", evaluate_anomaly, device, db, background_tasks)


def _retry_on_lock(db: Session, fn):
    """Run fn once more after a deadlock, a serialisation failure or a lock timeout. Nothing it does before its commit survives a rollback."""
    for attempt in (1, 2):
        try:
            return fn()
        except OperationalError as exc:
            if attempt == 2 or getattr(exc.orig, "pgcode", None) not in _RETRYABLE_SQLSTATES:
                raise
            logger.warning("a post is being retried after a database lock problem (%s)", getattr(exc.orig, "pgcode", ""))
            db.rollback()


@router.post("", response_model=TelemetryResponse, status_code=201)
def ingest_telemetry(
    payload: TelemetryIngest,
    background_tasks: BackgroundTasks,
    x_api_key: str = Header(...),
    # scope="function": the session is closed when this function returns, before the response is sent and before the
    # background tasks run. With the default scope it stays open until the tasks have finished, so a webhook or email
    # endpoint that hangs for its timeout holds a database connection (idle in a transaction) for every post
    db: Session = Depends(get_db, scope="function"),
):
    device = get_device_by_api_key(x_api_key, db)
    device_id = device.id
    # one device can post this often and no faster. 429 with Retry-After otherwise
    ingest_limit.check(device_id)

    # a deadlock, a serialisation failure or a lock timeout is retried once. Nothing the post does before its commit
    # leaves anything behind, so running it again costs nothing and a reading is never lost to a lock
    stored = _retry_on_lock(db, lambda: _store_reading(db, device_id, payload))

    if "refusal" in stored:
        kind, code, detail, status = stored["refusal"]
        if kind == "duplicate":
            # the exact pair last accepted: a retry of a post whose answer was lost. Answered as a success so the node
            # does not loop on it and nothing is stored
            return JSONResponse(status_code=200, content={"status": "duplicate", "stored": False, "detail": detail})
        # a counter no machine could reach is a bad value (422). An older or missing pair conflicts with what was accepted (409)
        raise ApiError(status, code, detail)
    device, reply = stored["device"], stored["reply"]
    if stored["backlog"]:
        # a backlog reading is stored and nothing more: no live broadcast, no rule, no anomaly window, no notification
        return reply
    # push to any WebSocket clients watching this device (runs after response is sent);
    # queued first so a slow email or SMS vendor cannot delay the dashboard's live update.
    background_tasks.add_task(ws_manager.broadcast, str(device.id), reply.model_dump_json())
    _after_commit(db, background_tasks, device, stored)
    return reply


# -- the batch route -------------------------------------------------------------------------------------------------------

# the most readings in one batch and the most bytes of body it may carry. A reading is at most about 5.5 kB (the bounded fault map,
# links and counters are the bulk) and usually about 1 kB, so 100 readings are 100 kB typically and 550 kB at the worst. The body
# limit a front proxy must allow for this route is BATCH_MAX_BODY_BYTES
BATCH_MAX_ITEMS = 100
BATCH_MAX_BODY_BYTES = 600_000


class BatchRequest(BaseModel):
    # each item is checked on its own below, so one bad reading is that item's result and does not fail the others
    readings: list[dict] = Field(min_length=1, max_length=BATCH_MAX_ITEMS)


class BatchItemResult(BaseModel):
    index: int
    # the status a single post of this reading would have answered: 201 stored, 200 duplicate, 409 or 422 refused
    status: int
    # the same in a word
    outcome: Literal["stored", "duplicate", "refused"]
    # stored: the new row's id. Null otherwise
    id: UUID | None = None
    # a refusal: a stable code and a sentence. A duplicate carries its sentence as detail and no code
    code: str | None = None
    detail: str | None = None
    # true when the reading was stored as a backlog reading (older than a live one) and so was not judged as current
    backlog: bool | None = None


class BatchResponse(BaseModel):
    results: list[BatchItemResult]
    stored: int
    duplicate: int
    refused: int


def _batch_size_guard(request: Request) -> None:
    length = request.headers.get("content-length")
    if length is not None and length.isdigit() and int(length) > BATCH_MAX_BODY_BYTES:
        raise ApiError(413, Code.BODY_TOO_LARGE, f"A batch body is at most {BATCH_MAX_BODY_BYTES} bytes. Send fewer readings per batch.")


def _store_batch(db: Session, device_id, readings: list[dict]) -> dict:
    """
    Every reading of a batch under ONE device lock, in order, one commit at the end.

    Each reading is checked and stored on its own inside a savepoint, so a bad one (invalid, refused by the replay rule or the
    observed_at bound or a database error) is that item's result and the others still go in. The replay rule is judged item by
    item against the pair the item before it left, so a batch sent twice answers "duplicate" for every item and a batch whose
    items run backwards is refused from the first stale one.
    """
    device = _lock_device(db, device_id)
    now = datetime.now(timezone.utc)
    results: list[dict] = []
    newest_live = None
    notices: list = []
    clipping = None
    for index, raw in enumerate(readings):
        try:
            payload = TelemetryIngest.model_validate(raw)
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {}
            loc = ".".join(str(x) for x in first.get("loc", ()))
            results.append({"index": index, "status": 422, "outcome": "refused", "code": "invalid_reading",
                            "detail": f"{loc}: {first.get('msg', 'not a valid reading')}" if loc else "not a valid reading"})
            continue
        # a reading without observed_at is stamped with the arrival time, a microsecond apart so the order in the batch is kept
        at = now + timedelta(microseconds=index)
        try:
            with db.begin_nested():
                refusal, resolved = _judge(device, payload, at)
                if refusal is not None:
                    kind, code, detail, status = refusal
                    results.append({"index": index, "status": status, "outcome": kind,
                                    "code": None if kind == "duplicate" else code, "detail": detail})
                    continue
                item = _build_item(db, device, payload, at, resolved)
                db.flush()
        except OperationalError:
            raise
        except Exception as exc:  # noqa: BLE001
            # one reading the database cannot take (a value the checks missed) must not cost the rest
            logger.warning("a batch reading was refused after a database error (%s)", type(exc).__name__)
            results.append({"index": index, "status": 422, "outcome": "refused", "code": "storage_error",
                            "detail": "this reading could not be stored"})
            continue
        results.append({"index": index, "status": 201, "outcome": "stored", "id": item["row"].id, "backlog": item["backlog"]})
        if not item["backlog"]:
            # every live reading may have opened an alert of its own (a fault, a restart loop), so their notices are kept together
            newest_live = item
            notices.extend(item["notices"])
            clipping = item["clipping"] or clipping
    # a batch is judged once, by its newest live reading: the rules and the anomaly window read the committed state, so judging every
    # item would only repeat the same answer a hundred times and queue a hundred times the notifications
    db.commit()
    if newest_live is not None:
        newest_live = {**newest_live, "notices": notices, "clipping": clipping}
    return {"device": device, "results": results, "live": newest_live}


@router.post("/batch", response_model=BatchResponse, dependencies=[Depends(_batch_size_guard)])
def ingest_batch(
    body: BatchRequest,
    background_tasks: BackgroundTasks,
    x_api_key: str = Header(...),
    db: Session = Depends(get_db, scope="function"),
):
    """
    Up to 100 readings from one device in one request, oldest first, with a result for each in order.

    Auth is the device key, as for a single post. The envelope answers 200 whenever the request itself is acceptable and every
    reading's own answer is in `results` (status stored, duplicate or refused and for a refusal the code, sentence and the status
    a single post would have answered). The wire contract of POST /api/v1/telemetry does not change.
    """
    device = get_device_by_api_key(x_api_key, db)
    device_id = device.id
    # its own allowance, counted in readings and not in requests (see services/ingest_limit.py)
    ingest_limit.check_batch(device_id, len(body.readings))
    out = _retry_on_lock(db, lambda: _store_batch(db, device_id, body.readings))
    results = out["results"]
    live = out["live"]
    if live is not None:
        device = out["device"]
        # only the newest live reading is judged and broadcast, once for the batch
        row = live["row"]
        reply = TelemetryResponse.model_validate(row)
        background_tasks.add_task(ws_manager.broadcast, str(device.id), reply.model_dump_json())
        _after_commit(db, background_tasks, device, live)
    counts = {"stored": 0, "duplicate": 0, "refused": 0}
    for r in results:
        counts[r["outcome"]] += 1
    return BatchResponse(results=[BatchItemResult(**r) for r in results], **counts)


@router.get("/export")
@limiter.limit(READ_LIMIT)
def export_telemetry(
    request: Request,
    device_id: uuid.UUID,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    # older names for from and to, accepted for this release
    from_ts: datetime | None = Query(default=None, deprecated=True),
    to_ts: datetime | None = Query(default=None, deprecated=True),
    # require auth here to prevent unauthenticated bulk data export.
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # same machine rule as GET /devices/{id}: a technician reads only their own or unowned machines
    get_device_for_read(db, user, device_id)
    from_ts, to_ts = from_ if from_ is not None else from_ts, to if to is not None else to_ts
    # the span is bounded so one request cannot read a machine's whole history, which is why from is required
    if from_ts is None:
        raise ApiError(422, Code.INVALID_RANGE, "from is required: an export covers at most 31 days")
    if window_span(from_ts, to_ts) > EXPORT_MAX_SPAN:
        raise ApiError(
            422, Code.INVALID_RANGE,
            f"an export covers at most {EXPORT_MAX_SPAN.days} days. Ask for a shorter range.",
        )
    # define /export before /{device_id} so FastAPI matches it as a literal
    # path segment rather than treating "export" as a device UUID.
    q = db.query(Telemetry).filter(Telemetry.device_id == device_id, Telemetry.recorded_at >= as_utc(from_ts))
    if to_ts:
        q = q.filter(Telemetry.recorded_at <= as_utc(to_ts))
    q = q.order_by(Telemetry.recorded_at.asc())

    columns = list(Telemetry.__table__.columns)

    # the slot is taken here, so a refused export answers 429 before the response starts and it is held until the
    # stream ends and not just until this function returns. It is released from the stream's own end and again from
    # the response's background task, which covers a client that leaves before the first row. Releasing twice is safe
    slot = heavy_read(user.id, "export")
    slot.__enter__()
    released = []

    def release():
        if not released:
            released.append(True)
            slot.__exit__(None, None, None)

    def body():
        try:
            # rows are read in batches and written out as they come, so memory holds one batch rather than the whole
            # export. The header is the table's column names or the short fallback when there are no rows
            buf = io.StringIO()
            writer = csv.writer(buf)
            count = 0
            for row in q.yield_per(EXPORT_BATCH):
                if count == 0:
                    writer.writerow([c.name for c in columns])
                writer.writerow(csv_safe.safe_row([getattr(row, c.name) for c in columns]))
                count += 1
                if count % EXPORT_BATCH == 0:
                    yield buf.getvalue()
                    buf.seek(0)
                    buf.truncate()
            if count == 0:
                writer.writerow(["id", "device_id", "recorded_at"])
            yield buf.getvalue()
        finally:
            release()

    filename = f"telemetry_{device_id}.csv"
    return StreamingResponse(
        body(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
        background=BackgroundTask(release),
    )


@router.get("/{device_id}", response_model=list[TelemetryResponse] | list[TelemetryBucketResponse])
@limiter.limit(READ_LIMIT)
def get_telemetry(
    request: Request,
    response: Response,
    device_id: uuid.UUID,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    # older names for from and to, accepted for this release
    from_ts: datetime | None = Query(default=None, deprecated=True),
    to_ts: datetime | None = Query(default=None, deprecated=True),
    node_type: str | None = None,
    # keyset paging: the readings before this one, newest first. Send the X-Next-Before of the previous page. Offset reaches back
    # at most 100,000 rows. A history this long carries no total: counting it would cost more than the page
    before: str | None = Query(default=None, description="Cursor from X-Next-Before: <ISO time>,<id>"),
    page: Page = Depends(Page.up_to(MAX_LIMIT, default=100)),
    bucket: int | None = Query(
        default=None,
        ge=MIN_BUCKET_SECONDS,
        le=MAX_BUCKET_SECONDS,
        description="bucket width in seconds. Returns one summarised row per bucket instead of raw rows; needs from_ts and a window of at most 31 days.",
    ),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # checked before anything else so a refused caller learns nothing from the other errors
    get_device_for_read(db, user, device_id)
    from_ts, to_ts = from_ if from_ is not None else from_ts, to if to is not None else to_ts
    if bucket is not None:
        # a bucketed answer is bounded by the window rather than by limit and offset, which are ignored
        if from_ts is None:
            raise ApiError(422, Code.INVALID_RANGE, "bucket needs from so the number of buckets is known")
        if window_span(from_ts, to_ts) > MAX_WINDOW:
            raise ApiError(
                422, Code.INVALID_RANGE,
                f"a bucketed request may cover at most {MAX_WINDOW.days} days. Use a shorter window.",
            )
        count = window_bucket_count(from_ts, to_ts, bucket)
        if count > MAX_BUCKETS:
            raise ApiError(
                422, Code.INVALID_RANGE,
                f"that window could return up to {count} buckets of {bucket} seconds and one request may return "
                f"at most {MAX_BUCKETS}. Use a larger bucket or a shorter window.",
            )
        try:
            # a bucketed read holds a database connection for up to its statement timeout, so it takes a slot
            with heavy_read(user.id, "bucket"):
                return bucketed_telemetry(db, device_id, bucket, from_ts, to_ts, node_type)
        except BucketQueryTimeout:
            raise ApiError(503, Code.QUERY_TOO_SLOW, "The readings took too long to summarise. Try a shorter range or a larger bucket.")

    q = db.query(Telemetry).filter(Telemetry.device_id == device_id)
    if from_ts:
        q = q.filter(Telemetry.recorded_at >= as_utc(from_ts))
    if to_ts:
        q = q.filter(Telemetry.recorded_at <= as_utc(to_ts))
    if node_type:
        q = q.filter(Telemetry.node_type == node_type)
    # newest first, ending in id so two readings stamped alike never swap between pages
    order = (Telemetry.recorded_at.desc(), Telemetry.id.desc())
    if before is not None:
        when, row_id = keyset.decode(before)
        q = q.filter(tuple_(Telemetry.recorded_at, Telemetry.id) < tuple_(when, row_id))
        rows = q.order_by(*order).limit(page.limit).all()
    else:
        rows = q.order_by(*order).offset(page.offset).limit(page.limit).all()
    keyset.set_next(response, rows, page.limit, "recorded_at")
    return rows


@router.get("/{device_id}/latest", response_model=TelemetryResponse)
@limiter.limit(READ_LIMIT)
def get_latest(
    request: Request,
    device_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_device_for_read(db, user, device_id)
    row = (
        db.query(Telemetry)
        .filter(Telemetry.device_id == device_id)
        .order_by(Telemetry.recorded_at.desc())
        .first()
    )
    if not row:
        raise ApiError(404, Code.TELEMETRY_NOT_FOUND, "No telemetry found for device")
    return row
