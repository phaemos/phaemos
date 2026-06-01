# Custom Hooks

| File | Purpose |
|---|---|
| useTelemetry.ts | Polls GET /telemetry/{deviceId} every 5s. Accepts fromTs, toTs, nodeType, limit options. |
| useAlerts.ts | Polls GET /alerts every 5s. Returns active alert list. |
| useTickets.ts | Polls GET /tickets every 5s. Returns ticket list with optional status filter. |
