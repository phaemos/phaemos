// the message the API wrote for a refused request, when it is meant for the person and not for a developer;
// only a client error (not sign-in, permission or rate limit, which describeApiError words better) counts.
// FastAPI sends a string for an error the route raised and a list for a body that failed validation.

interface Shape {
  response?: { status?: number; data?: { detail?: unknown } };
}

export function apiDetail(err: unknown): string | undefined {
  const res = (err as Shape | null)?.response;
  const status = res?.status;
  if (!status || status < 400 || status >= 500 || status === 401 || status === 403 || status === 429) return undefined;
  const detail = res?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d && typeof d === 'object' && typeof (d as { msg?: unknown }).msg === 'string' ? (d as { msg: string }).msg : ''))
      // pydantic prefixes the message of a value error
      .map((m) => m.replace(/^Value error, /, ''))
      .filter(Boolean);
    if (msgs.length) return msgs.join(' ');
  }
  return undefined;
}
