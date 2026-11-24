// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildTelemetryWsUrl, authFrame, MAX_FRAME } from './wsUrl.ts';

const id = '3f2504e0-4f89-41d3-9a0c-0305e82c3301';

test('targets the backend route outside /api/v1 with no query string', () => {
  const url = buildTelemetryWsUrl(id, 'http://localhost:8000');
  assert.equal(url, `ws://localhost:8000/ws/telemetry/${id}`);
  assert.ok(!url.includes('/api/v1'));
  assert.ok(!url.includes('?'));
});

test('uses wss for an https API and drops a trailing slash', () => {
  assert.equal(buildTelemetryWsUrl(id, 'https://api.phaemos.com/'), `wss://api.phaemos.com/ws/telemetry/${id}`);
});

test('the token goes in an auth frame', () => {
  assert.deepEqual(JSON.parse(authFrame('a+b/c=') ?? ''), { type: 'auth', token: 'a+b/c=' });
});

test('a frame over the limit is not sent', () => {
  assert.equal(authFrame('x'.repeat(MAX_FRAME)), null);
  assert.ok(authFrame('x'.repeat(100)) !== null);
});
