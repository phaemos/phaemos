import { parseRetryAfter, waitPhrase } from './retryAfter.ts';

// what a 429 from the sign-in and proof routes means (docs/api-reference.md, "Sign-in slowdown"). An account is never locked for good:
// wrong guesses make the place they came from wait, 30 seconds after the fifth and then longer and the answer carries Retry-After;
// separately each address may call /login 5 times a minute, which answers with an "error" field and no Retry-After.

// an account is never locked for good now: too many failures only make the place they came from wait and the API says how long
export const LOCKED_MESSAGE = 'Too many failed attempts. Wait a little and try again.';
export const RATE_LIMITED_MESSAGE = 'Too many attempts. Wait a minute and try again.';

// what a 429 says. A Retry-After header, when there is one, is the most exact thing the API gives: how long to wait. Without it the
// limit is read from the body ("Rate limit exceeded: 5 per 1 hour", in `detail` or in the older `error`) and said as it is for an hour
// or a day and a limit of a minute is "wait a minute". A sentence the API wrote for its own limit (changing the email too often) is
// shown as written. Nothing here looks for the word "locked": the API no longer locks an account and what to do comes from the status.
export function tooManyAttemptsMessage(body: unknown, retryAfterSeconds?: number | null): string {
  if (retryAfterSeconds && retryAfterSeconds > 0) return `Too many attempts. Try again in ${waitPhrase(retryAfterSeconds)}.`;
  const b = (body ?? {}) as { detail?: unknown; error?: unknown };
  const text = typeof b.detail === 'string' && b.detail.trim() ? b.detail : typeof b.error === 'string' ? b.error : '';
  const m = text.match(/(\d+) per (\d+) (hour|day)s?/i);
  if (m) return `Too many attempts. The limit is ${m[1]} for every ${m[2] === '1' ? '' : m[2] + ' '}${m[3].toLowerCase()}${m[2] === '1' ? '' : 's'}. Try again later.`;
  // a sentence the API wrote for its own limit is shown as it is, unless it is only the generic limit line
  if (text && /\s/.test(text.trim()) && !/rate limit/i.test(text)) return text;
  return RATE_LIMITED_MESSAGE;
}

// the plain sentence for a failed request that was a 429 or undefined for any other failure. The routes that count wrong
// guesses toward the lock (sign-in, change of password, two-step, change of email, deleting the account) all answer 429 once
// it is locked and a page shows this in place of a generic "too many requests".
export function lockedMessage(err: unknown): string | undefined {
  const res = (err as { response?: { status?: number; data?: unknown; headers?: Record<string, unknown> } } | null)?.response;
  if (res?.status !== 429) return undefined;
  return tooManyAttemptsMessage(res.data, parseRetryAfter(res.headers?.['retry-after']));
}
