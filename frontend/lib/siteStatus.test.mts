// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { failingParts, parseStatus } from './siteStatus.ts';

const ok = { status: 'operational', api: 'ok', database: 'ok', redis: 'ok', updated_at: '2026-11-22T10:00:00+00:00' };

test('a complete reply is read', () => {
  assert.deepEqual(parseStatus(ok), { api: 'ok', database: 'ok', redis: 'ok', updatedAt: '2026-11-22T10:00:00+00:00' });
});

test('a reply that is not the route answer is no answer', () => {
  assert.equal(parseStatus(null), null);
  assert.equal(parseStatus('<html>'), null);
  assert.equal(parseStatus({}), null);
  assert.equal(parseStatus({ ...ok, database: 'slow' }), null);
  assert.equal(parseStatus({ ...ok, updated_at: 5 }), null);
});

test('failing parts are named', () => {
  assert.deepEqual(failingParts(parseStatus(ok)!), []);
  assert.deepEqual(failingParts(parseStatus({ ...ok, database: 'error', redis: 'error' })!), ['Database', 'Cache']);
});
