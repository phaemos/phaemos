import math
import random
import uuid as uuid_module
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_db, engine
from app.models.device import Device
from app.models.telemetry import Telemetry
from app.models.user import User
from app.routes.auth import require_admin

router = APIRouter()

# I keep a single scheduler instance at module level so start/stop can
# reference the same instance without threading it through the request cycle.
_scheduler = BackgroundScheduler(daemon=True)
_demo_device_id: str | None = None
_tick: int = 0

# I create a dedicated SessionLocal here because the background job runs in a
# thread outside FastAPI's request lifecycle and cannot use Depends(get_db).
_SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _generate_reading(tick: int) -> dict:
    # I use a sine wave for temperature and humidity to mimic realistic sensor cycles.
    temperature = round(25 + 5 * math.sin(tick * 0.1), 2)
    humidity    = round(50 + 10 * math.sin(tick * 0.05 + 1), 2)
    vib_base    = random.uniform(0.01, 0.05)
    # 1-in-10 chance of an anomaly spike to exercise the alert rule evaluation.
    spike       = 0.5 if random.random() < 0.1 else 0.0
    return {
        "temperature": temperature,
        "humidity":    humidity,
        "vibration_x": round(vib_base + spike, 4),
        "vibration_y": round(random.uniform(0.01, 0.05), 4),
        "vibration_z": round(random.uniform(0.01, 0.05), 4),
        "light_level": round(random.uniform(100.0, 800.0), 1),
    }


def _ingest_demo_reading() -> None:
    global _tick, _demo_device_id
    if not _demo_device_id:
        return
    db = _SessionLocal()
    try:
        device = db.query(Device).filter(Device.id == _demo_device_id).first()
        if not device:
            return
        reading = _generate_reading(_tick)
        _tick += 1
        row = Telemetry(device_id=device.id, anomaly_score=0.0, is_anomaly=False, **reading)
        db.add(row)
        device.last_seen = datetime.now(timezone.utc)
        device.status    = "online"
        db.commit()
    finally:
        db.close()


@router.post("/demo/start")
def start_demo(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    global _demo_device_id, _tick

    # I reuse an existing Demo Node rather than creating duplicates on repeated calls.
    device = db.query(Device).filter(Device.name == "Demo Node").first()
    if not device:
        device = Device(
            name="Demo Node",
            type="esp32",
            location="Virtual",
            api_key=str(uuid_module.uuid4()),
        )
        db.add(device)
        db.commit()
        db.refresh(device)

    _demo_device_id = str(device.id)
    _tick = 0

    if not _scheduler.running:
        _scheduler.start()

    # I remove the existing job before adding to avoid duplicate interval jobs
    # if the client calls /demo/start more than once.
    if _scheduler.get_job("demo_ingest"):
        _scheduler.remove_job("demo_ingest")
    _scheduler.add_job(_ingest_demo_reading, "interval", seconds=5, id="demo_ingest")

    return {"device_id": str(device.id), "api_key": device.api_key, "status": "started"}


@router.post("/demo/stop")
def stop_demo(_admin: User = Depends(require_admin)):
    global _demo_device_id
    if _scheduler.running and _scheduler.get_job("demo_ingest"):
        _scheduler.remove_job("demo_ingest")
    _demo_device_id = None
    return {"status": "stopped"}
