import { test } from 'node:test';
import assert from 'node:assert/strict';
import { deprecationWarning, warnDeprecated } from './deprecation.ts';

const headers = { deprecation: 'true', sunset: 'Sat, 20 Feb 2027 00:00:00 GMT', link: '</api/v1/users>; rel="successor-version"' };

test('a deprecated answer names the route, the date and the new path', () => {
  const t = deprecationWarning('get', '/auth/users', headers);
  assert.match(t ?? '', /GET \/auth\/users is a deprecated API path/);
  assert.match(t ?? '', /20 Feb 2027/);
  assert.match(t ?? '', /\/api\/v1\/users/);
});

test('an ordinary answer says nothing', () => {
  assert.equal(deprecationWarning('get', '/users', {}), null);
  assert.equal(deprecationWarning('get', '/users', { deprecation: 'false' }), null);
});

test('it reads headers through get as well', () => {
  const bag = { get: (n: string) => (headers as Record<string, string>)[n.toLowerCase()] };
  assert.ok(deprecationWarning('post', '/auth/invite', bag));
});

test('it logs once for each route and only in development', () => {
  const log: string[] = [];
  assert.equal(warnDeprecated('get', '/a', headers, false, (m) => log.push(m)), false);
  assert.equal(warnDeprecated('get', '/a', headers, true, (m) => log.push(m)), true);
  assert.equal(warnDeprecated('get', '/a', headers, true, (m) => log.push(m)), false);
  assert.equal(log.length, 1);
});
