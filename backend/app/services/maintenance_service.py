"""Whether a machine is inside a maintenance window. It lives here and not in the route file so services do not import routes."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.maintenance import MaintenanceWindow


def is_in_maintenance(db: Session, device_id: UUID) -> bool:
    """Return True if device_id is currently inside an active maintenance window."""
    now = datetime.now(timezone.utc)
    return (
        db.query(MaintenanceWindow)
        .filter(
            MaintenanceWindow.start_at <= now,
            MaintenanceWindow.end_at >= now,
            MaintenanceWindow.suppress_alerts.is_(True),
            or_(
                MaintenanceWindow.device_id == device_id,
                MaintenanceWindow.device_id.is_(None),
            ),
        )
        .first()
    ) is not None
