# ORM Models

SQLAlchemy table definitions. Each file maps to one database table.

| File | Table | Description |
|---|---|---|
| device.py | devices | Registered nodes with API key, status, expected post interval and link state |
| device_health.py | device_health | The latest vitals and faults a node reported, lost posts and the boot times a restart loop is counted from |
| telemetry.py | telemetry | All sensor readings with anomaly scores, the node's post counter and clock and a quality record of faults |
| alert.py | alerts + alert_rules | Fired alert events (machine or monitoring, with an optional sensor key) and threshold rule config |
| ticket.py | tickets | Maintenance work order tickets |
| user.py | users | User accounts with role (admin/technician/viewer) |
