// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildCsp } from './csp.mjs';

function directive(policy: string, name: string): string {
  const found = policy.split('; ').find((part) => part.startsWith(`${name} `));
  assert.ok(found, `${name} is missing from the policy`);
  return found;
}

// whole entries of one directive are compared, so a longer host that only contains the expected one cannot pass
function allows(policy: string, name: string, source: string): boolean {
  return directive(policy, name).split(' ').slice(1).some((entry) => entry === source);
}

test('with no vendor values only the site and the API are allowed', () => {
  const csp = buildCsp({ apiUrl: 'https://api.phaemos.com/v1' });
  assert.ok(!csp.includes('cloudflare'));
  assert.ok(!csp.includes('google'));
  assert.ok(!csp.includes('frame-src'));
  assert.equal(directive(csp, 'connect-src'), "connect-src 'self' https://api.phaemos.com wss://api.phaemos.com");
});

test('falls back to the local API when no url is given', () => {
  const csp = buildCsp();
  assert.ok(directive(csp, 'connect-src').includes('http://localhost:8000 ws://localhost:8000'));
});

test('a Turnstile site key adds the script and the frame', () => {
  const csp = buildCsp({ turnstileSiteKey: 'site-key' });
  assert.ok(allows(csp, 'script-src', 'https://challenges.cloudflare.com'));
  assert.equal(directive(csp, 'frame-src'), 'frame-src https://challenges.cloudflare.com');
  assert.ok(!csp.includes('googletagmanager'));
});

test('a Google Analytics id adds the tag, beacon and image sources', () => {
  const csp = buildCsp({ gaId: 'G-TEST000000' });
  assert.ok(allows(csp, 'script-src', 'https://www.googletagmanager.com'));
  assert.ok(allows(csp, 'img-src', 'https://*.google-analytics.com'));
  assert.ok(allows(csp, 'connect-src', 'https://*.google-analytics.com'));
  assert.ok(allows(csp, 'connect-src', 'https://*.analytics.google.com'));
  assert.ok(allows(csp, 'connect-src', 'https://analytics.google.com'));
  assert.ok(!allows(csp, 'connect-src', 'https://*.google.com'));
  assert.ok(!csp.includes('cloudflare'));
  assert.ok(!csp.includes('frame-src'));
});

test('both vendors can be on together and the fixed directives stay', () => {
  const csp = buildCsp({ turnstileSiteKey: 'k', gaId: 'G-TEST000000' });
  assert.ok(allows(csp, 'script-src', 'https://challenges.cloudflare.com'));
  assert.ok(allows(csp, 'frame-src', 'https://challenges.cloudflare.com'));
  assert.ok(allows(csp, 'script-src', 'https://www.googletagmanager.com'));
  assert.ok(csp.includes("object-src 'none'"));
  assert.ok(csp.includes("frame-ancestors 'none'"));
});

test('empty strings count as unset', () => {
  const csp = buildCsp({ turnstileSiteKey: '', gaId: '' });
  assert.ok(!csp.includes('cloudflare'));
  assert.ok(!csp.includes('google'));
});

test("'unsafe-eval' is only in the development policy", () => {
  assert.ok(!buildCsp().includes('unsafe-eval'));
  assert.ok(!buildCsp({ gaId: 'G-TEST000000', turnstileSiteKey: 'k' }).includes('unsafe-eval'));
  assert.ok(buildCsp({ development: true }).includes("'unsafe-eval'"));
});

test('the policy fixes the base address and where a form may post', () => {
  const csp = buildCsp();
  assert.ok(csp.includes("base-uri 'self'"));
  assert.ok(csp.includes("form-action 'self'"));
});

test('the dashboard policy allows no inline script except the request nonce', async () => {
  const { buildNonceCsp } = await import('./csp.mjs');
  const csp = buildNonceCsp({ nonce: 'abc123', apiUrl: 'https://api.phaemos.com' });
  const script = csp.split('; ').find((d) => d.startsWith('script-src')) ?? '';
  assert.ok(script.includes("'nonce-abc123'") && script.includes("'strict-dynamic'"));
  assert.ok(!script.includes('unsafe-inline') && !script.includes('unsafe-eval'));
  for (const d of ["object-src 'none'", "base-uri 'self'", "form-action 'self'", "frame-ancestors 'none'"]) assert.ok(csp.includes(d), d);
  assert.ok(allows(csp, 'connect-src', 'wss://api.phaemos.com'));
  assert.ok(buildNonceCsp({ nonce: 'n', development: true }).includes("'unsafe-eval'"));
});

test('the theme file is allowed by its hash and the hash is of the file on disk', async () => {
  const { buildNonceCsp } = await import('./csp.mjs');
  const { themeScriptHash } = await import('./themeHash.mjs');
  const hash = themeScriptHash();
  assert.match(hash, /^sha256-[A-Za-z0-9+/]+=*$/);
  assert.ok(buildNonceCsp({ nonce: 'n', scriptHashes: [hash] }).includes(`'${hash}'`));
});
