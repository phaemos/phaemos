# Custom Hooks

| File | Purpose |
| --- | --- |
| useWebSocketTelemetry.ts | Opens a WS connection to /ws/telemetry/{deviceId}. Reconnects with exponential backoff (1/2/4/8/16s, max 5 attempts). No retry on close code 1008 (auth failure). |
| useShellStatus.ts | Feeds the app shell. Reads GET /auth/me once (name, email and role, for the Admin link and the user row) and polls GET /health/summary every 15s (fleet counts for the fleet status and the active alert count for the Alerts badge). |
| useSignedIn.ts | Says whether the `signed_in` marker cookie is present, so the public site can offer "Open dashboard" instead of "Sign in". The server render assumes signed out. |
| useApiResource.ts | `useApiResource<T>(path, { params, intervalMs, what, enabled })` returns `{ data, error, loading, retry }` for one GET endpoint through `lib/api.ts`. A failed poll keeps the earlier data. See `components/ui/README.md` |
| useSpinnerVisible.ts | `useSpinnerVisible(active)` is true 200 ms after work starts and stays for at least 300 ms once shown, so a spinner never flashes |
| useRole.ts | The signed-in role read from the access token, for choosing which controls to offer. The API enforces the role |
| useOwnerContext.ts | Names for a machine's owner: every user for an admin, the signed-in user for anyone else |
| useToast.ts | The toast provider and `useToast()` |
| useRole.ts | also exports `useCanWrite()`, false for a viewer, so a write control can be hidden with a reason in words |
