// what a webhook is, how its last delivery is put into words and what the test route answers. No import, so the tests can load it.

export type WebhookFormat = 'chat' | 'json';

export interface Webhook {
  id: string;
  name: string;
  url: string;
  enabled: boolean;
  format?: WebhookFormat;
  template: string | null;
  disabled_reason?: string | null;
  has_secret?: boolean;
  last_delivery_at?: string | null;
  last_status?: number | null;
  last_error?: string | null;
  consecutive_failures?: number;
}

export const WEBHOOK_FORMATS: { value: WebhookFormat; label: string; sentence: string }[] = [
  { value: 'chat', label: 'Chat message', sentence: 'A short message for Slack, Discord or Teams. We recognise the service from the address and format it for that service. You can write your own wording.' },
  { value: 'json', label: 'Signed JSON', sentence: 'The full alert as JSON, for a program to read. Each delivery is signed with a secret that is shown once, so the receiver can check it came from us.' },
];

export function formatOf(w: { format?: string | null }): WebhookFormat {
  return w.format === 'json' ? 'json' : 'chat';
}

export function formatLabel(f: WebhookFormat): string {
  return f === 'json' ? 'Signed JSON' : 'Chat message';
}

// where the receiver's instructions for checking a signature are written
export const VERIFY_LINK = 'https://github.com/phaemos/phaemos/blob/main/docs/api-reference.md#verifying-the-signature';

export type DeliveryTone = 'none' | 'ok' | 'failing' | 'off';

export interface DeliveryState {
  tone: DeliveryTone;
  // the word that carries the state, so colour is never the only signal
  label: string;
  // a sentence that says what happened. The time is left to the caller, which draws it as a time element
  detail: string;
}

// the last delivery in words. `last_status` is the HTTP status the receiver answered, null when nothing answered.
export function deliveryState(w: Pick<Webhook, 'enabled' | 'disabled_reason' | 'last_delivery_at' | 'last_status' | 'last_error' | 'consecutive_failures'>): DeliveryState {
  const fails = Math.max(0, w.consecutive_failures ?? 0);
  if (!w.enabled && w.disabled_reason) return { tone: 'off', label: 'Switched off', detail: `Switched off because ${w.disabled_reason.replace(/\.$/, '')}. Switch it on again after you fix it.` };
  if (!w.enabled) return { tone: 'off', label: 'Off', detail: 'Alerts are not sent to it while it is off.' };
  if (!w.last_delivery_at) return { tone: 'none', label: 'Nothing sent yet', detail: 'Send a test to see that it arrives.' };
  const answered = typeof w.last_status === 'number' ? `The receiver answered ${w.last_status}.` : 'Nothing answered.';
  if (fails > 0 || w.last_error) {
    // "http 500" only repeats the status that is already in the sentence
    const reason = w.last_error && !/^http \d{3}$/i.test(w.last_error.trim()) ? w.last_error : '';
    const why = reason ? ` ${reason.replace(/\.$/, '')}.` : '';
    const run = fails > 1 ? ` ${fails} deliveries in a row have failed.` : '';
    return { tone: 'failing', label: 'Failing', detail: `${answered}${why}${run}` };
  }
  return { tone: 'ok', label: 'Delivered', detail: answered };
}

export interface TestOutcome {
  ok: boolean;
  status: number | null;
  elapsedMs: number | null;
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

// the answer of POST /webhooks/{id}/test. A success has `ok: true`. Anything else is not a success, so an answer without it is read as one that failed.
export function testOutcome(data: unknown): TestOutcome {
  const d = data && typeof data === 'object' ? (data as Record<string, unknown>) : {};
  return { ok: d.ok === true, status: num(d.status), elapsedMs: num(d.elapsed_ms) };
}

export function testSentence(name: string, o: TestOutcome): string {
  const took = o.elapsedMs === null ? '' : ` in ${o.elapsedMs} ms`;
  const status = o.status === null ? '' : ` The receiver answered ${o.status}.`;
  return o.ok ? `The test to ${name} was delivered${took}.${status}` : `The test to ${name} was not delivered${took}.${status}`;
}

// a failed test is 502 `webhook_delivery_failed` with `errors: [{status, elapsed_ms}]`
export function failedTest(err: unknown): { status: number | null; elapsedMs: number | null } | null {
  const body = (err as { response?: { data?: unknown } } | null)?.response?.data;
  if (!body || typeof body !== 'object') return null;
  const b = body as Record<string, unknown>;
  if (b.code !== 'webhook_delivery_failed') return null;
  const first = Array.isArray(b.errors) && b.errors[0] && typeof b.errors[0] === 'object' ? (b.errors[0] as Record<string, unknown>) : {};
  return { status: num(first.status), elapsedMs: num(first.elapsed_ms) };
}

// the secret from an answer that makes or rotates one or null when there is none
export function secretFromAnswer(data: unknown): string | null {
  const s = data && typeof data === 'object' ? (data as { secret?: unknown }).secret : null;
  return typeof s === 'string' && s.length > 0 ? s : null;
}

export const SECRET_WARNING = 'This is the only time this secret is shown. It cannot be read again. If it is lost, make a new one, which stops the old one working at once.';
export const SECRET_WARNING_ROTATED = 'This is the only time this secret is shown. It cannot be read again. The old secret has stopped signing, so the receiver rejects our deliveries until it has this one.';
