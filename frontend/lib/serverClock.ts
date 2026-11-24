// the server's clock against the browser's. A browser clock can be minutes or hours wrong and every "how old is this" on a
// dashboard (the headline of a chart, "no reading for 4 min", the window's right edge) must be measured on the server's time,
// because the readings are stamped with it. This keeps a small running estimate of the offset (server minus browser) taken from
// ordinary responses: the Date header where the browser can read it and otherwise the machine reads, which carry the last post
// and the seconds since it. The estimate is the median of the last few samples, so one slow response cannot move it. No import.

const KEEP = 7;
let samples: number[] = [];

function median(values: readonly number[]): number {
  if (values.length === 0) return 0;
  const s = [...values].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

// one sample: the server said it was `serverMs` at some point between the request leaving and the answer arriving, which is
// taken as the middle of that span
export function noteServerTime(serverMs: number, sentAt: number, receivedAt: number): void {
  if (!Number.isFinite(serverMs) || !Number.isFinite(sentAt) || !Number.isFinite(receivedAt)) return;
  samples = [...samples, serverMs - (sentAt + receivedAt) / 2].slice(-KEEP);
}

// the offset to add to the browser's clock to get the server's, in milliseconds
export function serverOffsetMs(): number {
  return median(samples);
}

export function serverNow(browserNow: number = Date.now()): number {
  return browserNow + serverOffsetMs();
}

export function resetServerClock(): void {
  samples = [];
}

interface HeaderLike {
  get?: (name: string) => unknown;
  [key: string]: unknown;
}

function readHeader(headers: HeaderLike | undefined, name: string): string | null {
  if (!headers) return null;
  const v = typeof headers.get === 'function' ? headers.get(name) : headers[name];
  return typeof v === 'string' ? v : null;
}

interface DeviceMoment {
  last_seen?: string | null;
  seconds_since_last_post?: number | null;
}

// a machine read says when the node last posted and how many seconds ago that was, both on the server's clock, so their sum is the
// server's "now" at the moment it answered. The seconds are whole, so the sum is up to a second behind.
function deviceMoment(data: unknown): number | null {
  const list = Array.isArray(data) ? data : [data];
  for (const d of list as DeviceMoment[]) {
    if (d && typeof d === 'object' && typeof d.seconds_since_last_post === 'number' && typeof d.last_seen === 'string') {
      const t = Date.parse(d.last_seen);
      if (Number.isFinite(t)) return t + d.seconds_since_last_post * 1000 + 500;
    }
  }
  return null;
}

// feed one response in. The Date header is used when the browser can read it (it needs Access-Control-Expose-Headers: Date across
// addresses). Without it a machine read serves instead.
export function noteResponse(headers: HeaderLike | undefined, data: unknown, sentAt: number, receivedAt: number): void {
  const date = readHeader(headers, 'date');
  if (date) {
    const t = Date.parse(date);
    // the header has a resolution of a second and is cut, not rounded
    if (Number.isFinite(t)) {
      noteServerTime(t + 500, sentAt, receivedAt);
      return;
    }
  }
  const moment = deviceMoment(data);
  if (moment !== null) noteServerTime(moment, sentAt, receivedAt);
}
