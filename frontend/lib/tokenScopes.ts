// the three scopes of an API token and what each one allows, in a sentence for the person making one (docs/api-reference.md,
// "API tokens"). Only an admin account can make an admin token, so a non-admin is not offered it.
export const TOKEN_SCOPES = [
  { value: 'read', label: 'Read', sentence: 'Can look at machines, readings, alerts and tickets and change nothing.' },
  { value: 'operate', label: 'Operate', sentence: 'Read and the day-to-day changes your role allows: acknowledge or resolve an alert, work on a ticket and edit a machine\'s details.' },
  { value: 'admin', label: 'Admin', sentence: 'Operate and the administration work that needs no fresh proof: register or delete a machine, alert rules, maintenance windows, the audit log and model retraining.' },
] as const;

export type TokenScope = (typeof TOKEN_SCOPES)[number]['value'];

export function scopesFor(role: string | null | undefined): readonly (typeof TOKEN_SCOPES)[number][] {
  return role === 'admin' ? TOKEN_SCOPES : TOKEN_SCOPES.filter((s) => s.value !== 'admin');
}

export const DEFAULT_TOKEN_DAYS = 90;
export const MAX_LIVE_TOKENS = 20;

// a number of days the API accepts (1 to 365) or an error sentence
export function daysProblem(value: string): string | null {
  if (!/^\d+$/.test(value.trim())) return 'Enter a whole number of days from 1 to 365.';
  const n = Number(value);
  return n >= 1 && n <= 365 ? null : 'Enter a whole number of days from 1 to 365.';
}

// the sentence that follows every action that ends sessions: tokens go with them
export const TOKENS_REVOKED_NOTE = 'Every API token you have made stops working too.';

export const EXPIRY_WARNING_DAYS = 14;

// whole days from now to a moment, rounded up. Negative once it has passed
export function daysUntil(iso: string, nowMs: number): number {
  return Math.ceil((Date.parse(iso) - nowMs) / 86_400_000);
}

export type TokenState = 'ok' | 'soon' | 'expired';

export function tokenState(expiresAt: string, nowMs: number): TokenState {
  const days = daysUntil(expiresAt, nowMs);
  if (Date.parse(expiresAt) <= nowMs) return 'expired';
  return days <= EXPIRY_WARNING_DAYS ? 'soon' : 'ok';
}
