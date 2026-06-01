# ORM Models

SQLAlchemy table definitions. Each file maps to one database table.

| File | Table | Description |
|---|---|---|
| device.py | devices | Registered nodes with API key and status |
| telemetry.py | telemetry | All sensor readings with anomaly scores |
| alert.py | alerts + alert_rules | Fired alert events and threshold rule config |
| ticket.py | tickets | Maintenance work order tickets |
| user.py | users | User accounts with role (admin/technician/viewer) |
