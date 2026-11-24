// the backend mounts the telemetry WebSocket at the root, outside the
// versioned /api/v1 prefix (see backend/app/routes/ws.py), next to / and /status.
export const TELEMETRY_WS_PATH = '/ws/telemetry';

// the access token is never in the address: it goes in the first frame (see authFrame), because an address is recorded by
// proxies and logs.
export function buildTelemetryWsUrl(deviceId: string, base: string = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'): string {
  // swap the scheme so the WS connection uses the same host/port as the REST API.
  // http becomes ws and https becomes wss.
  const wsBase = base.replace(/\/+$/, '').replace(/^http/, 'ws');
  return `${wsBase}${TELEMETRY_WS_PATH}/${encodeURIComponent(deviceId)}`;
}

// the API refuses a frame over 4096 characters, so one is never sent
export const MAX_FRAME = 4096;

// the first text frame. Null when it would be too long
export function authFrame(token: string): string | null {
  const frame = JSON.stringify({ type: 'auth', token });
  return frame.length > MAX_FRAME ? null : frame;
}
