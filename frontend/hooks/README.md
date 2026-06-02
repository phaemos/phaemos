# Custom Hooks

| File | Purpose |
| --- | --- |
| useTelemetry.ts | Polls GET /telemetry/{deviceId} every 5s. Accepts fromTs, toTs, nodeType, limit options. |
| useAlerts.ts | Polls GET /alerts every 5s. Returns active alert list. |
| useTickets.ts | Polls GET /tickets every 5s. Returns ticket list with optional status filter. |
| useWebSocketTelemetry.ts | Opens a WS connection to /ws/telemetry/{deviceId}. Reconnects with exponential backoff (1/2/4/8/16s, max 5 attempts). No retry on close code 1008 (auth failure). |
