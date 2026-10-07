// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildTelemetryWsUrl } from './wsUrl.ts';

const id = '3f2504e0-4f89-41d3-9a0c-0305e82c3301';

test('targets the backend route outside /api/v1', () => {
  const url = buildTelemetryWsUrl(id, 'abc', 'http://localhost:8000');
  assert.equal(url, `ws://localhost:8000/ws/telemetry/${id}?token=abc`);
  assert.ok(!url.includes('/api/v1'));
});

test('uses wss for an https API and drops a trailing slash', () => {
  const url = buildTelemetryWsUrl(id, 'abc', 'https://api.phaemos.com/');
  assert.equal(url, `wss://api.phaemos.com/ws/telemetry/${id}?token=abc`);
});

test('encodes the token', () => {
  const url = buildTelemetryWsUrl(id, 'a+b/c=', 'http://localhost:8000');
  assert.ok(url.endsWith('?token=a%2Bb%2Fc%3D'));
});
