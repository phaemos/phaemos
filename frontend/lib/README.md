# Lib

| File | Purpose |
|---|---|
| api.ts | Axios instance with baseURL from NEXT_PUBLIC_API_URL. Attaches JWT from localStorage on every request. |
| wsUrl.ts | Builds the live telemetry WebSocket URL, `/ws/telemetry/{deviceId}` on the API host, outside `/api/v1`. Tested by `wsUrl.test.mts` (`npm test`). |
| utils.ts | Shared utility functions (date formatting, class merging, etc.) |
