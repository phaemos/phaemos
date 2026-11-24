// what the API's public /status route returns and how the status page reads it. The route checks a database query
// and a Redis ping, so the parts below are the only ones it can name.

export type PartState = 'ok' | 'error';

export interface StatusReport {
  api: PartState;
  database: PartState;
  redis: PartState;
  updatedAt: string;
}

export type PartKey = 'api' | 'database' | 'redis';

export const PARTS: { key: PartKey; label: string; what: string }[] = [
  { key: 'api', label: 'API', what: 'Answers this request' },
  { key: 'database', label: 'Database', what: 'Runs a test query' },
  { key: 'redis', label: 'Cache', what: 'Answers a ping' },
];

// how long the page waits for the API before it says it could not reach it
export const CHECK_TIMEOUT_MS = 8000;
export const CHECK_INTERVAL_MS = 30_000;

function isState(value: unknown): value is PartState {
  return value === 'ok' || value === 'error';
}

// a reply that is not shaped like the route's answer counts as no answer, so a proxy error page or an HTML 200
// from a wrong address ends in "could not reach" and never in a half-filled table
export function parseStatus(raw: unknown): StatusReport | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const r = raw as Record<string, unknown>;
  if (!isState(r.api) || !isState(r.database) || !isState(r.redis)) return null;
  if (typeof r.updated_at !== 'string') return null;
  return { api: r.api, database: r.database, redis: r.redis, updatedAt: r.updated_at };
}

export function failingParts(report: StatusReport): string[] {
  return PARTS.filter((p) => report[p.key] !== 'ok').map((p) => p.label);
}
