import csv
import io
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Header
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.device import Device
from app.models.telemetry import Telemetry
from app.models.user import User
from app.routes.auth import get_current_user
from app.schemas.telemetry import TelemetryIngest, TelemetryResponse
from app.services.ml_service import score_reading
from app.services.alert_service import evaluate_rules
from app.services import ws_manager

router = APIRouter()


def get_device_by_api_key(api_key: str, db: Session) -> Device:
    # I use the device API key as the auth mechanism for firmware ingest requests.
    device = db.query(Device).filter(Device.api_key == api_key).first()
    if not device:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return device


@router.post("", response_model=TelemetryResponse, status_code=201)
def ingest_telemetry(
    payload: TelemetryIngest,
    background_tasks: BackgroundTasks,
    x_api_key: str = Header(...),
    db: Session = Depends(get_db),
):
    device = get_device_by_api_key(x_api_key, db)

    # I derive reading from the full payload so alert rules can evaluate any v2
    # sensor metric, not just the original 6. device_id is excluded because the
    # device is already resolved to device.id before this point.
    reading = payload.model_dump(exclude={"device_id"})

    # I score first so the row stores both the reading and model decision atomically.
    anomaly_score, is_anomaly = score_reading(reading)

    row = Telemetry(
        device_id=device.id,
        anomaly_score=anomaly_score,
        is_anomaly=is_anomaly,
        **reading,
    )
    db.add(row)

    device.last_seen = datetime.now(timezone.utc)
    device.status = "online"

    db.commit()
    db.refresh(row)

    # I evaluate alert rules after persistence so alerts reference committed state.
    evaluate_rules(device, reading, db)

    # Serialize before scheduling - the DB session closes after this function returns.
    row_json = TelemetryResponse.model_validate(row).model_dump_json()
    # Push to any WebSocket clients watching this device (runs after response is sent).
    background_tasks.add_task(ws_manager.broadcast, str(device.id), row_json)

    return row


@router.get("/export")
def export_telemetry(
    device_id: uuid.UUID,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    # I require auth here to prevent unauthenticated bulk data export.
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # I define /export before /{device_id} so FastAPI matches it as a literal
    # path segment rather than treating "export" as a device UUID.
    q = db.query(Telemetry).filter(Telemetry.device_id == device_id)
    if from_ts:
        q = q.filter(Telemetry.recorded_at >= from_ts)
    if to_ts:
        q = q.filter(Telemetry.recorded_at <= to_ts)
    rows = q.order_by(Telemetry.recorded_at.asc()).all()

    # I stream the CSV without loading all rows into a Python list at once -
    # io.StringIO acts as an in-memory buffer that csv.writer can write into.
    buf = io.StringIO()
    writer = csv.writer(buf)

    # Header row derived from the column names of the first row's mapping
    if rows:
        writer.writerow(rows[0].__table__.columns.keys())
    else:
        writer.writerow(["id", "device_id", "recorded_at"])

    for row in rows:
        writer.writerow([getattr(row, c.name) for c in row.__table__.columns])

    buf.seek(0)
    filename = f"telemetry_{device_id}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{device_id}", response_model=list[TelemetryResponse])
def get_telemetry(
    device_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    node_type: str | None = None,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # I use from_ts/to_ts rather than 'from' (reserved keyword) for the query param names.
    q = db.query(Telemetry).filter(Telemetry.device_id == device_id)
    if from_ts:
        q = q.filter(Telemetry.recorded_at >= from_ts)
    if to_ts:
        q = q.filter(Telemetry.recorded_at <= to_ts)
    if node_type:
        q = q.filter(Telemetry.node_type == node_type)
    return (
        q.order_by(Telemetry.recorded_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/{device_id}/latest", response_model=TelemetryResponse)
def get_latest(
    device_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(Telemetry)
        .filter(Telemetry.device_id == device_id)
        .order_by(Telemetry.recorded_at.desc())
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="No telemetry found for device")
    return row
