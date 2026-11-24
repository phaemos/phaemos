// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
// relativeTime.ts is now a thin re-export of format.ts, so the same cases run against formatRelative
import { formatRelative as relativeTime } from './format.ts';

const now = Date.parse('2026-11-22T12:00:00Z');

test('labels by the largest sensible unit', () => {
  assert.equal(relativeTime('2026-11-22T11:59:40Z', now), 'just now');
  assert.equal(relativeTime('2026-11-22T11:55:00Z', now), '5 min ago');
  assert.equal(relativeTime('2026-11-22T09:00:00Z', now), '3 h ago');
  assert.equal(relativeTime('2026-11-20T12:00:00Z', now), '2 d ago');
});

test('a time in the future reads as just now', () => {
  assert.equal(relativeTime('2026-11-22T12:05:00Z', now), 'just now');
});

test('handles a missing or invalid time', () => {
  assert.equal(relativeTime(null, now), 'never');
  assert.equal(relativeTime('not a date', now), 'unknown');
});
