from datetime import datetime, timezone, timedelta
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import Page, set_total
from app.errors import ApiError, Code
from app.limiter import limiter, named
from app.schemas.ml import (AlertVerdict, AlertVerdictReply, AmbientSource, AmbientSourceReply, MoveAccepted, ModelStatusSummary,
                            RetrainStarted, ScoreReply)
from app.models.alert import Alert
from app.models.device import Device
from app.models.telemetry import Telemetry
from app.models.user import User
from app.schemas.telemetry import TelemetryIngest, TelemetryResponse
from app.routes.auth import fresh_proof, get_current_user, require_admin
from app.services import ml_service
from app.tasks import model_retrain
from app.services import audit_service
from app.services.access import get_device_for_read, require_device_read, require_device_write

router = APIRouter()

# 1-hour cooldown enforced in memory so rapid re-submissions do not thrash training.
_last_retrain: datetime | None = None
_COOLDOWN = timedelta(hours=1)
# a retrain runs one at a time in this process. A second request while one runs is refused by the cooldown anyway
# and a retrain longer than the cooldown must not overlap itself


@router.post("/retrain", status_code=202, response_model=RetrainStarted)
@limiter.limit(named("sensitive"))
def retrain(
    request: Request,
    background_tasks: BackgroundTasks,
    admin=Depends(require_admin),
):
    global _last_retrain
    now = datetime.now(timezone.utc)

    if _last_retrain and (now - _last_retrain) < _COOLDOWN:
        remaining = int((_last_retrain + _COOLDOWN - now).total_seconds() // 60)
        raise ApiError(429, Code.RETRAIN_COOLDOWN, f"Retrain cooldown active. Try again in {remaining} minutes.")

    _last_retrain = now
    background_tasks.add_task(model_retrain.run_retrain, str(admin.id), "manual")
    return {"detail": "Retrain started. The result is at GET /api/v1/ml/status when it finishes."}


@router.get("/status", response_model=ModelStatusSummary)
def model_status_route(current_user: User = Depends(get_current_user)):
    """What is in service and the outcome of the latest retrain, accepted or refused, with the reason in words."""
    summary = ml_service.bundle_summary()
    summary["schedule"] = model_retrain.schedule()
    return summary


@router.post("/score", response_model=ScoreReply)
def score(
    payload: TelemetryIngest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    Score a reading by hand, to test the model. Admin only, as the API reference says.

    When device_id names a machine that exists, the machine access rule is applied to it (404 or 403 as on any machine
    route) and its own model is used. An id that is not a machine scores with the node type's and the general models.
    """
    reading = payload.model_dump(exclude={"device_id"})
    machine_id = None
    try:
        wanted = UUID(str(payload.device_id))
    except ValueError:
        wanted = None
    if wanted is not None and db.query(Device.id).filter(Device.id == wanted).first():
        get_device_for_read(db, admin, wanted)
        machine_id = str(wanted)
    anomaly_score, is_anomaly = ml_service.score_reading(reading, device_id=machine_id, track=False)
    return {"anomaly_score": anomaly_score, "is_anomaly": is_anomaly}


@router.get("/anomalies/{device_id}", response_model=list[TelemetryResponse])
def anomaly_history(
    device_id: UUID,
    response: Response,
    page: Page = Depends(Page.up_to(1000, default=100)),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    get_device_for_read(db, current_user, device_id)
    query = (
        db.query(Telemetry)
        .filter(Telemetry.device_id == device_id, Telemetry.is_anomaly)
        .order_by(Telemetry.recorded_at.desc(), Telemetry.id)
    )
    set_total(response, query.count())
    return query.offset(page.offset).limit(page.limit).all()


@router.post("/machines/{device_id}/accept-move", response_model=MoveAccepted)
@limiter.limit(named("sensitive"))
def accept_move(
    request: Request,
    device_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    # the move bound is what stops a slow forged walk of a machine's normal, so lifting it is a signed-in admin's decision
    # with fresh proof (the password and the two-step code in the body) and never something an API token can do
    _proof: None = Depends(fresh_proof("accept a larger move of a machine's normal")),
):
    """
    Let the next retrain move this machine's normal past the bound and re-anchor it there. Admin only, with fresh proof.

    A retrain refuses a model that would move a machine's normal further than the bound from the model in service or from
    the first model accepted for it, because a slow walk is what a drifting fault or a forged sensor looks like. A person
    who knows the change is real (a new product, a season, a repair) accepts it here and then retrains.
    """
    get_device_for_read(db, admin, device_id)
    ml_service.accept_move(str(device_id), str(admin.id))
    audit_service.log_action(db, user_id=str(admin.id), action="model_move_accepted", resource="device",
                             resource_id=str(device_id),
                             detail=f"accepted by {admin.role} {admin.id}: the next retrain may move this machine's normal "
                                    "past the bound and re-anchor it")
    return {"detail": "Accepted. The next retrain may move this machine's normal and re-anchor it. Retrain to apply it."}


@router.post("/alerts/{alert_id}/verdict", response_model=AlertVerdictReply)
@limiter.limit(named("write"))
def alert_verdict(
    request: Request,
    alert_id: UUID,
    body: AlertVerdict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Record a person's verdict on a machine alert: a real fault (true) or not one (false).

    The people who may resolve the alert may give it (an admin or a technician on a machine they may change), with a
    session or an operate token. Only a model alert confirmed as a real fault keeps its readings out of the model's
    training. An unconfirmed one does not, so a machine whose normal changed is retrained on it and its alert can clear.
    """
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    device = db.query(Device).filter(Device.id == alert.device_id).first() if alert is not None else None
    if alert is None or device is None or alert.category != "machine":
        raise ApiError(404, Code.ALERT_NOT_FOUND, "No machine alert has that id")
    # an alert on a machine the caller may not read looks like one that does not exist, as on the alert routes
    require_device_read(current_user, device, detail="No machine alert has that id", code=Code.ALERT_NOT_FOUND)
    require_device_write(current_user, device)
    before = alert.fault_confirmed
    alert.fault_confirmed = body.fault
    db.commit()
    reply = {"id": alert.id, "fault_confirmed": alert.fault_confirmed}
    audit_service.log_action(db, user_id=str(current_user.id), action="alert_verdict", resource="alert",
                             resource_id=str(alert_id),
                             detail=f"{'a real fault' if body.fault else 'not a fault'} (was {before}), "
                                    f"given by {current_user.role} {current_user.id}")
    return reply


@router.put("/machines/{device_id}/ambient-source", response_model=AmbientSourceReply)
@limiter.limit(named("write"))
def set_ambient_source(
    request: Request,
    device_id: UUID,
    body: AmbientSource,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    Set (or clear with null) the node whose air temperature is this machine's ambient reference. Admin only.

    The source must be another machine the caller may read and should stand in the same place. The next retrain models
    this machine's temperatures as their rise above that reading, so a warmer room is not read as a warmer machine.
    """
    device = get_device_for_read(db, admin, device_id)
    if body.source_id is not None:
        if body.source_id == device_id:
            raise ApiError(422, Code.VALIDATION_FAILED, "A machine cannot be its own ambient source")
        get_device_for_read(db, admin, body.source_id)
    before = device.ambient_source_id
    device.ambient_source_id = body.source_id
    db.commit()
    audit_service.log_action(db, user_id=str(admin.id), action="ambient_source_set", resource="device",
                             resource_id=str(device_id), detail=f"ambient source {before} to {body.source_id}")
    return {"device_id": device_id, "source_id": body.source_id,
            "detail": "Set. The next retrain uses it as this machine's ambient reference."}
