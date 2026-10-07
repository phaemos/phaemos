// the backend mounts the telemetry WebSocket at the root, outside the
// versioned /api/v1 prefix (see backend/app/routes/ws.py), next to / and /status.
export const TELEMETRY_WS_PATH = '/ws/telemetry';

export function buildTelemetryWsUrl(
  deviceId: string,
  token: string,
  base: string = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000',
): string {
  // swap the scheme so the WS connection uses the same host/port as the REST API.
  // http becomes ws and https becomes wss.
  const wsBase = base.replace(/\/+$/, '').replace(/^http/, 'ws');
  return `${wsBase}${TELEMETRY_WS_PATH}/${encodeURIComponent(deviceId)}?token=${encodeURIComponent(token)}`;
}
