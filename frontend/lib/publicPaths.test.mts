// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { scopeAnalytics } from './publicPaths.ts';

const view = (url: string) => ({ type: 'pageview', url });

test('public site pages are counted', () => {
  assert.equal(scopeAnalytics(view('https://phaemos.com/'))?.url, 'https://phaemos.com/');
  assert.equal(scopeAnalytics(view('https://phaemos.com/privacy'))?.url, 'https://phaemos.com/privacy');
  assert.equal(scopeAnalytics(view('https://phaemos.com/blog/hardware-deep-dive'))?.url, 'https://phaemos.com/blog/hardware-deep-dive');
  assert.equal(scopeAnalytics(view('/cookies'))?.url, '/cookies');
});

test('a query string and a fragment are dropped from a counted address', () => {
  assert.equal(scopeAnalytics(view('https://phaemos.com/changelog?type=fixed#x'))?.url, 'https://phaemos.com/changelog');
});

test('dashboard, sign-in and invitation addresses are never counted', () => {
  for (const u of ['/dashboard', '/devices/3f2a', '/alerts', '/tickets', '/admin', '/profile', '/login', '/accept-invite?token=abc', 'https://dashboard.phaemos.com/devices/9c1']) {
    assert.equal(scopeAnalytics(view(u)), null, u);
  }
});

test('an address that is not a path is dropped', () => {
  assert.equal(scopeAnalytics(view('http://[')), null);
});

// ---- two addresses ----

import { APP_PATHS, appPathOf, cleanPath, hostKind, linkTo, normaliseHost, parseSplitConfig, routeRequest } from './publicPaths.ts';

const SPLIT = parseSplitConfig('https://phaemos.com', 'https://dashboard.phaemos.com');
const LOCAL = parseSplitConfig('http://phaemos.test:3200', 'http://dashboard.phaemos.test:3200');
const route = (host: string | null, pathname: string, search = '', config = SPLIT) => routeRequest({ host, pathname, search }, config);

test('one address when the values are equal, missing or unreadable', () => {
  assert.equal(parseSplitConfig('https://phaemos.com', 'https://phaemos.com').split, false);
  assert.equal(parseSplitConfig('https://phaemos.com', 'https://PHAEMOS.com/').split, false);
  assert.equal(parseSplitConfig('https://phaemos.com', undefined).split, false);
  assert.equal(parseSplitConfig(undefined, 'https://dashboard.phaemos.com').split, false);
  assert.equal(parseSplitConfig('not a url', 'https://dashboard.phaemos.com').split, false);
  assert.equal(parseSplitConfig('ftp://phaemos.com', 'https://dashboard.phaemos.com').split, false);
  assert.equal(SPLIT.split, true);
});

test('single mode passes every request', () => {
  const single = parseSplitConfig(undefined, undefined);
  for (const p of ['/', '/dashboard', '/about', '/login', '/devices/1']) assert.deepEqual(route('localhost:3000', p, '', single), { type: 'pass' });
});

test('host names compare in one form', () => {
  assert.equal(normaliseHost('DASHBOARD.Phaemos.com'), 'dashboard.phaemos.com');
  assert.equal(normaliseHost('dashboard.phaemos.com:443'), 'dashboard.phaemos.com');
  assert.equal(normaliseHost('dashboard.phaemos.com.'), 'dashboard.phaemos.com');
  assert.equal(normaliseHost('localhost:3200'), 'localhost:3200');
  assert.equal(hostKind('Dashboard.Phaemos.COM', SPLIT), 'app');
  assert.equal(hostKind('phaemos.com:443', SPLIT), 'site');
  assert.equal(hostKind('www.phaemos.com', SPLIT), 'site');
  assert.equal(hostKind('phaemos.vercel.app', SPLIT), 'other');
  assert.equal(hostKind(null, SPLIT), 'other');
  assert.equal(hostKind('dashboard.phaemos.test:3200', LOCAL), 'app');
  assert.equal(hostKind('dashboard.phaemos.test', LOCAL), 'other');
});

test('an unknown host is never redirected', () => {
  for (const p of ['/', '/dashboard', '/about', '/login']) assert.deepEqual(route('preview-abc.vercel.app', p), { type: 'pass' });
});

test('on the app host the overview is at the root', () => {
  assert.deepEqual(route('dashboard.phaemos.com', '/'), { type: 'rewrite', pathname: '/dashboard' });
  assert.deepEqual(route('dashboard.phaemos.com', '/dashboard'), { type: 'redirect', url: 'https://dashboard.phaemos.com/' });
  assert.deepEqual(route('dashboard.phaemos.com', '/dashboard/', '?node=esp32'), { type: 'redirect', url: 'https://dashboard.phaemos.com/?node=esp32' });
});

test('on the app host a public site page moves to the site host', () => {
  assert.deepEqual(route('dashboard.phaemos.com', '/about'), { type: 'redirect', url: 'https://phaemos.com/about' });
  assert.deepEqual(route('dashboard.phaemos.com', '/blog/hardware', '?x=1'), { type: 'redirect', url: 'https://phaemos.com/blog/hardware?x=1' });
  assert.deepEqual(route('dashboard.phaemos.com', '/changelog/2.4.1/'), { type: 'redirect', url: 'https://phaemos.com/changelog/2.4.1' });
  assert.deepEqual(route('dashboard.phaemos.com', '/privacy'), { type: 'redirect', url: 'https://phaemos.com/privacy' });
});

test('on the app host the dashboard pages and the sign-in pages pass', () => {
  for (const p of ['/devices', '/devices/abc', '/alerts', '/tickets', '/compare', '/admin', '/profile', '/login', '/accept-invite', '/nope']) {
    assert.deepEqual(route('dashboard.phaemos.com', p), { type: 'pass' }, p);
  }
});

test('on the site host a dashboard page moves to the app host', () => {
  assert.deepEqual(route('phaemos.com', '/dashboard'), { type: 'redirect', url: 'https://dashboard.phaemos.com/' });
  assert.deepEqual(route('phaemos.com', '/devices/abc', '?tab=x'), { type: 'redirect', url: 'https://dashboard.phaemos.com/devices/abc?tab=x' });
  assert.deepEqual(route('phaemos.com', '/login'), { type: 'redirect', url: 'https://dashboard.phaemos.com/login' });
  assert.deepEqual(route('phaemos.com', '/accept-invite'), { type: 'redirect', url: 'https://dashboard.phaemos.com/accept-invite' });
  assert.deepEqual(route('phaemos.com', '/admin/'), { type: 'redirect', url: 'https://dashboard.phaemos.com/admin' });
});

test('on the site host the public pages pass', () => {
  for (const p of ['/', '/about', '/docs', '/changelog/2.4.1', '/blog/x', '/nope']) assert.deepEqual(route('phaemos.com', p), { type: 'pass' }, p);
});

test('www moves to the plain site address and keeps the path and query', () => {
  assert.deepEqual(route('www.phaemos.com', '/about', '?a=1'), { type: 'redirect', url: 'https://phaemos.com/about?a=1', permanent: true });
  assert.deepEqual(route('www.phaemos.com', '/'), { type: 'redirect', url: 'https://phaemos.com', permanent: true });
  assert.deepEqual(route('www.phaemos.com', '/dashboard'), { type: 'redirect', url: 'https://dashboard.phaemos.com/' });
});

test('static files, framework paths and the crawler files are never redirected', () => {
  for (const host of ['phaemos.com', 'dashboard.phaemos.com']) {
    for (const p of ['/_next/static/chunk.js', '/_vercel/insights/script.js', '/.well-known/security.txt', '/robots.txt', '/favicon.ico', '/icon.png', '/opengraph-image.png', '/brand/phaemos-emblem-dark.png', '/api/x']) {
      assert.deepEqual(route(host, p), { type: 'pass' }, `${host}${p}`);
    }
  }
  assert.deepEqual(route('phaemos.com', '/sitemap.xml'), { type: 'pass' });
});

test('the app host has no sitemap', () => {
  assert.deepEqual(route('dashboard.phaemos.com', '/sitemap.xml'), { type: 'notfound' });
});

test('a host with a port is compared with the port', () => {
  assert.deepEqual(route('dashboard.phaemos.test:3200', '/about', '', LOCAL), { type: 'redirect', url: 'http://phaemos.test:3200/about' });
  assert.deepEqual(route('phaemos.test:3200', '/devices', '', LOCAL), { type: 'redirect', url: 'http://dashboard.phaemos.test:3200/devices' });
  assert.deepEqual(route('dashboard.phaemos.test:3200', '/', '', LOCAL), { type: 'rewrite', pathname: '/dashboard' });
});

test('trailing slashes and doubled slashes never reach another host', () => {
  assert.equal(cleanPath('/about/'), '/about');
  assert.equal(cleanPath('//evil.example/x'), '/evil.example/x');
  assert.equal(cleanPath('///'), '/');
  assert.deepEqual(route('dashboard.phaemos.com', '//evil.example/about'), { type: 'pass' });
  const d = route('dashboard.phaemos.com', '/about//x');
  assert.deepEqual(d, { type: 'redirect', url: 'https://phaemos.com/about/x' });
});

test('a redirect always begins with a configured origin', () => {
  const origins = ['https://phaemos.com', 'https://dashboard.phaemos.com'];
  for (const host of ['phaemos.com', 'dashboard.phaemos.com', 'www.phaemos.com']) {
    for (const p of ['/about', '/dashboard', '/login', '//x.y/z', '/blog/../../x', '/devices/%2F%2Fevil']) {
      const d = route(host, p, '?next=https://evil.example');
      if (d.type === 'redirect') assert.ok(origins.some((o) => d.url === o || d.url.startsWith(o + '/')), d.url);
    }
  }
});

test('every dashboard path is known to the router', () => {
  for (const p of APP_PATHS) assert.notDeepEqual(route('phaemos.com', p), { type: 'pass' }, p);
});

test('links are relative on one address and absolute when split', () => {
  const single = parseSplitConfig(undefined, undefined);
  assert.equal(linkTo('site', '/docs', single), '/docs');
  assert.equal(linkTo('app', '/dashboard', single), '/dashboard');
  assert.equal(linkTo('site', '/docs', SPLIT), 'https://phaemos.com/docs');
  assert.equal(linkTo('site', '/', SPLIT), 'https://phaemos.com');
  assert.equal(linkTo('app', '/login', SPLIT), 'https://dashboard.phaemos.com/login');
  assert.equal(linkTo('app', '/dashboard', SPLIT), 'https://dashboard.phaemos.com/');
  assert.equal(appPathOf('/dashboard', SPLIT), '/');
  assert.equal(appPathOf('/devices', SPLIT), '/devices');
  assert.equal(appPathOf('/dashboard', single), '/dashboard');
});

test('with two addresses nothing on the dashboard address is counted, not even its root', () => {
  assert.equal(scopeAnalytics(view('https://dashboard.phaemos.com/'), 'dashboard.phaemos.com'), null);
  assert.equal(scopeAnalytics(view('https://dashboard.phaemos.com/about'), 'dashboard.phaemos.com'), null);
  assert.equal(scopeAnalytics(view('https://phaemos.com/about'), 'dashboard.phaemos.com')?.url, 'https://phaemos.com/about');
  assert.equal(scopeAnalytics(view('https://phaemos.com/'), 'dashboard.phaemos.com')?.url, 'https://phaemos.com/');
});

test('a dashboard page ending in a file extension is still a dashboard page', () => {
  assert.deepEqual(route('phaemos.com', '/devices/x.png'), { type: 'redirect', url: 'https://dashboard.phaemos.com/devices/x.png' });
  assert.deepEqual(route('phaemos.com', '/logo.png'), { type: 'pass' });
});

test('a trailing dot before a port is dropped', () => {
  assert.equal(hostKind('dashboard.phaemos.test.:3210', parseSplitConfig('http://phaemos.test:3210', 'http://dashboard.phaemos.test:3210')), 'app');
});

test('the dashboard, sign-in and invitation pages are the private surface', async () => {
  const { isPrivateSurface } = await import('./publicPaths.ts');
  const single = parseSplitConfig(undefined, undefined);
  const split = parseSplitConfig('https://phaemos.com', 'https://dashboard.phaemos.com');
  for (const p of ['/dashboard', '/devices/abc', '/login', '/accept-invite', '/admin/', '/profile']) assert.equal(isPrivateSurface(p, 'other', single), true, p);
  for (const p of ['/', '/about', '/privacy', '/blog/x', '/status']) assert.equal(isPrivateSurface(p, 'other', single), false, p);
  assert.equal(isPrivateSurface('/', 'app', split), true);
  assert.equal(isPrivateSurface('/', 'site', split), false);
  assert.equal(isPrivateSurface('/about', 'site', split), false);
});
