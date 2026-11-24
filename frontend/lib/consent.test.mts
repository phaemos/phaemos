// run with `npm test`, which uses the Node test runner with type stripping.
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import {
  CONSENT_KEY,
  clearAnalyticsCookies,
  closeConsentPrompt,
  getPromptOpen,
  getServerConsent,
  isAnalyticsCookie,
  openConsentPrompt,
  readConsent,
  resetConsentForTests,
  setAnalyticsDisabled,
  subscribeConsent,
  writeConsent,
} from './consent.ts';

// a minimal browser: a window that can add and remove listeners plus a storage
// that can be made to throw, like a private window.
function installWindow(options: { throwing?: boolean } = {}) {
  const data = new Map<string, string>();
  const handlers = new Set<(e: unknown) => void>();
  const localStorage = {
    getItem(key: string) {
      if (options.throwing) throw new Error('blocked');
      return data.has(key) ? data.get(key)! : null;
    },
    setItem(key: string, value: string) {
      if (options.throwing) throw new Error('blocked');
      data.set(key, value);
    },
  };
  const win = {
    localStorage,
    addEventListener: (_: string, fn: (e: unknown) => void) => handlers.add(fn),
    removeEventListener: (_: string, fn: (e: unknown) => void) => handlers.delete(fn),
  };
  (globalThis as unknown as { window: unknown }).window = win;
  return { data, handlers, win };
}

beforeEach(() => {
  resetConsentForTests();
  delete (globalThis as unknown as { window?: unknown }).window;
  delete (globalThis as unknown as { document?: unknown }).document;
});

test('server rendering reports unknown and does not throw', () => {
  assert.equal(readConsent(), 'unknown');
  assert.equal(getServerConsent(), 'unknown');
  assert.equal(getPromptOpen(), false);
});

test('reads unset, then the stored choice', () => {
  const { data } = installWindow();
  assert.equal(readConsent(), 'unset');
  data.set(CONSENT_KEY, 'accepted');
  assert.equal(readConsent(), 'accepted');
});

test('ignores a stored value that is not a choice', () => {
  const { data } = installWindow();
  data.set(CONSENT_KEY, 'maybe');
  assert.equal(readConsent(), 'unset');
});

test('a write in this tab notifies subscribers without a storage event', () => {
  installWindow();
  let calls = 0;
  const off = subscribeConsent(() => { calls += 1; });
  writeConsent('accepted');
  assert.equal(calls, 1);
  assert.equal(readConsent(), 'accepted');
  off();
  writeConsent('declined');
  assert.equal(calls, 1);
});

test('a storage event for the key from another tab notifies subscribers', () => {
  const { handlers } = installWindow();
  let calls = 0;
  const off = subscribeConsent(() => { calls += 1; });
  assert.equal(handlers.size, 1);
  const [handler] = [...handlers];
  handler({ key: CONSENT_KEY });
  handler({ key: 'theme' });
  handler({ key: null });
  assert.equal(calls, 2);
  off();
  assert.equal(handlers.size, 0);
});

test('keeps the choice for the visit when storage throws', () => {
  installWindow({ throwing: true });
  assert.equal(readConsent(), 'unset');
  assert.doesNotThrow(() => writeConsent('declined'));
  assert.equal(readConsent(), 'declined');
});

test('a key removed in another tab is not hidden by an earlier write', () => {
  const { data } = installWindow();
  writeConsent('accepted');
  data.delete(CONSENT_KEY);
  assert.equal(readConsent(), 'unset');
});

test('the settings prompt opens and closes and notifies', () => {
  installWindow();
  let calls = 0;
  subscribeConsent(() => { calls += 1; });
  openConsentPrompt();
  assert.equal(getPromptOpen(), true);
  closeConsentPrompt();
  assert.equal(getPromptOpen(), false);
  assert.equal(calls, 2);
});

test('sets the documented disable switch for the id', () => {
  const { win } = installWindow();
  setAnalyticsDisabled('G-TEST000000', true);
  assert.equal((win as unknown as Record<string, unknown>)['ga-disable-G-TEST000000'], true);
  setAnalyticsDisabled('G-TEST000000', false);
  assert.equal((win as unknown as Record<string, unknown>)['ga-disable-G-TEST000000'], false);
});

test('recognises the analytics cookie names only', () => {
  assert.ok(isAnalyticsCookie('_ga'));
  assert.ok(isAnalyticsCookie('_ga_ABC123'));
  assert.ok(!isAnalyticsCookie('token'));
  assert.ok(!isAnalyticsCookie('_gat'));
  assert.ok(!isAnalyticsCookie('refresh_token'));
});

// a fake document whose cookie setter records every string written to it
function installCookies(hostname: string, jar: string) {
  const written: string[] = [];
  (globalThis as unknown as { window: unknown }).window = { location: { hostname } };
  (globalThis as unknown as { document: unknown }).document = {
    get cookie() {
      return jar;
    },
    set cookie(value: string) {
      written.push(value);
    },
  };
  return written;
}

const EXPIRED = 'expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';

test('expires _ga cookies on the host and each parent domain and leaves others alone', () => {
  const written = installCookies('www.example.com', 'token=abc; _ga=GA1.1.1; _ga_ABC123=GS1; theme=dark');
  clearAnalyticsCookies();
  assert.deepEqual(written, [
    `_ga=; ${EXPIRED}`,
    `_ga=; ${EXPIRED}; domain=www.example.com`,
    `_ga=; ${EXPIRED}; domain=example.com`,
    `_ga_ABC123=; ${EXPIRED}`,
    `_ga_ABC123=; ${EXPIRED}; domain=www.example.com`,
    `_ga_ABC123=; ${EXPIRED}; domain=example.com`,
  ]);
  assert.ok(!written.some((w) => w.startsWith('token=') || w.startsWith('theme=')));
});

test('on localhost only the host-only cookie is expired', () => {
  const written = installCookies('localhost', '_ga=GA1.1.1; session=x');
  clearAnalyticsCookies();
  assert.deepEqual(written, [`_ga=; ${EXPIRED}`]);
});

test('writes nothing when there is no analytics cookie', () => {
  const written = installCookies('www.example.com', 'token=abc; _gat=1');
  clearAnalyticsCookies();
  assert.deepEqual(written, []);
});
