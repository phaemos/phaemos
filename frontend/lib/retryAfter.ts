// how long to wait, from a Retry-After header: a number of seconds or an HTTP date. The API answers 429 with it when a sign-in, a proof
// or a code is slowed down. Nothing here says "locked": an account is never locked for good, it is only made to wait.

export function parseRetryAfter(value: unknown, nowMs: number = Date.now()): number | null {
  if (value === null || value === undefined) return null;
  const text = String(value).trim();
  if (!text) return null;
  let seconds: number;
  if (/^\d+$/.test(text)) {
    seconds = Number(text);
  } else {
    const at = Date.parse(text);
    if (Number.isNaN(at)) return null;
    seconds = Math.ceil((at - nowMs) / 1000);
  }
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  // a day is the longest any wait here can be and a larger value is a fault to be ignored and not counted down
  return Math.min(seconds, 86_400);
}

// the wait on a failed request, if it was a 429 that carries one
export function retryAfterOf(err: unknown): number | null {
  const res = (err as { response?: { status?: number; headers?: Record<string, unknown> & { get?: (name: string) => unknown } } } | null)?.response;
  if (res?.status !== 429) return null;
  const raw = res.headers?.['retry-after'] ?? res.headers?.get?.('retry-after');
  return parseRetryAfter(raw);
}

// "30 seconds", "1 minute", "2 minutes", "1 hour": for a sentence, rounded up so the person never tries a moment too early
export function waitPhrase(seconds: number): string {
  const s = Math.max(1, Math.ceil(seconds));
  if (s < 60) return `${s} ${s === 1 ? 'second' : 'seconds'}`;
  if (s < 3600) {
    const m = Math.ceil(s / 60);
    return `${m} ${m === 1 ? 'minute' : 'minutes'}`;
  }
  const h = Math.ceil(s / 3600);
  return `${h} ${h === 1 ? 'hour' : 'hours'}`;
}
