// fuzzes the pure router (lib/publicPaths.ts). Every redirect must begin with a configured origin and parse to one and
// following the decisions from any start must end within a few hops. A fixed seed repeats a failure. Sized to run in a
// few seconds: the first version of this ran 11 million inputs by hand and found only the loop the "www" cases cover here.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseSplitConfig, routeRequest, APP_PATHS, SITE_PATHS, safeNextPath, nextFor } from './publicPaths.ts';

type Config = ReturnType<typeof parseSplitConfig>;

const configs: Config[] = [
  parseSplitConfig('https://phaemos.com', 'https://dashboard.phaemos.com'),
  parseSplitConfig('http://phaemos.test:3200', 'http://dashboard.phaemos.test:3200'),
  parseSplitConfig('https://phaemos.com/', 'https://dashboard.phaemos.com/some/path?x=1'),
  parseSplitConfig('https://dashboard.phaemos.com', 'https://phaemos.com'),
  parseSplitConfig('https://www.phaemos.com', 'https://dashboard.phaemos.com'),
  parseSplitConfig('https://phaemos.com', 'https://www.phaemos.com'),
  parseSplitConfig('https://user:pw@phaemos.com', 'https://dashboard.phaemos.com'),
];

const hostsFor = (c: Config) => [
  c.siteHost, c.appHost, `www.${c.siteHost}`, `www.${c.appHost}`, c.siteHost.toUpperCase(), `${c.siteHost}.`, `${c.appHost}.`,
  `${c.siteHost}:443`, `${c.appHost}:8443`, `${c.appHost}.:443`, `evil.example@${c.appHost}`, `${c.appHost}@evil.example`,
  `${c.appHost}.evil.example`, `evil${c.appHost}`, '[::1]', 'localhost:3000', 'preview-x.vercel.app', '', null, undefined,
  `${c.appHost}, ${c.siteHost}`, ` ${c.appHost} `, `${c.appHost}/`, `www.www.${c.siteHost}`, `www.${c.siteHost}.`,
];

const bits = ['', '/', '//', '\\', '/\\', '\\\\', '/%2F', '%5c%5c', '/..', '/%2e%2e', '@', ':', '#', '?', '%0d%0a', '\n', 'evil.example', 'https://evil.example', 'javascript:alert(1)', '。'];
const bases = ['', ...APP_PATHS, ...SITE_PATHS, '/', '/Dashboard', '/sitemap.xml', '/robots.txt', '/api/x', '/_next/x', '/.well-known/x', '/x.png', '/devices/x.png', '/nope'];

let seed = 20261122;
const rnd = () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 2 ** 32;
const pick = <T,>(a: T[]): T => a[Math.floor(rnd() * a.length)];
const alphabet = ['/', '/', '\\', '.', '..', '%2F', '%5C', '@', ':', '?', '#', 'evil.example', 'login', 'dashboard', 'devices', 'about', 'www.', 'app.', '%', '%0a', ' ', 'a', '//', 'https://', '.png', 'api/', '_next/'];
const randomPath = () => Array.from({ length: 1 + Math.floor(rnd() * 8) }, () => pick(alphabet)).join('');

function check(host: string | null | undefined, path: string, search: string, c: Config): void {
  const seen = new Set<string>();
  let h = host, p = path, s = search;
  for (let i = 0; i < 10; i++) {
    const key = `${h}|${p}|${s}`;
    assert.ok(!seen.has(key), `loop from ${JSON.stringify([host, path, search])}: ${[...seen].join(' -> ')}`);
    seen.add(key);
    const d = routeRequest({ host: h, pathname: p, search: s }, c);
    if (d.type !== 'redirect') return;
    const url = new URL(d.url);
    assert.ok([c.siteOrigin, c.appOrigin].includes(url.origin), `redirect leaves the configured origins: ${d.url}`);
    assert.ok([c.siteOrigin, c.appOrigin].some((o) => d.url === o || d.url.startsWith(`${o}/`) || d.url.startsWith(`${o}?`)), d.url);
    h = url.host; p = url.pathname; s = url.search;
  }
  assert.fail(`more than 10 hops from ${JSON.stringify([host, path, search])}`);
}

test('structured fuzz: redirects stay on a configured origin and never loop', () => {
  for (const c of configs) {
    for (const host of hostsFor(c)) {
      for (const b of bases) for (const x of bits) {
        check(host, b + x, '', c);
        check(host, x + b, '?next=https://evil.example', c);
      }
    }
  }
});

test('random fuzz: the same properties over random paths', () => {
  for (const c of configs) {
    const hosts = hostsFor(c);
    for (let i = 0; i < 12000; i++) check(pick(hosts), randomPath(), rnd() < 0.5 ? '' : `?${randomPath()}`, c);
  }
});

test('a www site address does not redirect to itself', () => {
  const c = parseSplitConfig('https://www.phaemos.com', 'https://dashboard.phaemos.com');
  assert.deepEqual(routeRequest({ host: 'www.phaemos.com', pathname: '/privacy' }, c), { type: 'pass' });
  // the plain host is not one of the two addresses here, so it is left alone
  assert.deepEqual(routeRequest({ host: 'phaemos.com', pathname: '/privacy' }, c), { type: 'pass' });
});

test('single mode never redirects', () => {
  for (const c of [parseSplitConfig(undefined, undefined), parseSplitConfig('https://phaemos.com', 'https://phaemos.com'), parseSplitConfig('https://phaemos.com', ''), parseSplitConfig('HTTPS://PHAEMOS.COM./', 'https://phaemos.com:443')]) {
    for (const b of bases) for (const x of bits) assert.deepEqual(routeRequest({ host: 'phaemos.com', pathname: b + x, search: '?x' }, c), { type: 'pass' });
  }
});

test('the page asked for before sign-in is accepted only as a dashboard path', () => {
  for (const ok of ['/devices', '/devices/abc?tab=x', '/alerts?category=temperature', '/admin', '/profile', '/tickets/12', '/compare']) assert.equal(safeNextPath(ok), ok);
  for (const bad of ['', null, undefined, '//evil.example', '/\\evil.example', 'https://evil.example', 'javascript:alert(1)', '/login', '/accept-invite', '/about', '/', '/devices/../../x', '/devices//x', '/devices\r\nX: 1', '/%2F%2Fevil', '/devices/' + 'a'.repeat(600)]) {
    assert.equal(safeNextPath(bad as string | null | undefined), null, String(bad));
  }
  assert.equal(nextFor('/devices/abc', '?tab=x'), '/devices/abc?tab=x');
  assert.equal(nextFor('/dashboard'), null);
  assert.equal(nextFor('/'), null);
});
