// run with `npm test`, which uses the Node test runner with type stripping.
// the zone is fixed so the absolute formats do not depend on the machine running the tests.
process.env.TZ = 'UTC';

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatCount, formatDate, formatDateTime, formatDateTimeExact, formatRelative } from './format.ts';

const now = Date.parse('2026-11-22T12:00:00Z');

test('formatDate writes day, short month and year', () => {
  assert.equal(formatDate('2026-11-22T00:10:05Z'), '22 Nov 2026');
  assert.equal(formatDate('2026-03-05'), '5 Mar 2026');
});

test('formatDateTime uses the 24-hour clock', () => {
  assert.equal(formatDateTime('2026-11-22T00:10:05Z'), '22 Nov 2026, 00:10');
  assert.equal(formatDateTime('2026-11-22T15:45:00Z'), '22 Nov 2026, 15:45');
});

test('formatDateTimeExact adds the seconds', () => {
  assert.equal(formatDateTimeExact('2026-11-22T00:10:05Z'), '22 Nov 2026, 00:10:05');
});

test('every format accepts a Date or a number', () => {
  const ms = Date.parse('2026-11-22T00:10:05Z');
  assert.equal(formatDateTime(new Date(ms)), '22 Nov 2026, 00:10');
  assert.equal(formatDate(ms), '22 Nov 2026');
});

test('absolute formats return an empty string for a missing or invalid value', () => {
  for (const f of [formatDate, formatDateTime, formatDateTimeExact]) {
    assert.equal(f(null), '');
    assert.equal(f(undefined), '');
    assert.equal(f('not a date'), '');
  }
});

test('formatRelative labels by the largest sensible unit', () => {
  assert.equal(formatRelative('2026-11-22T11:59:40Z', now), 'just now');
  assert.equal(formatRelative('2026-11-22T11:55:00Z', now), '5 min ago');
  assert.equal(formatRelative('2026-11-22T09:00:00Z', now), '3 h ago');
  assert.equal(formatRelative('2026-11-20T12:00:00Z', now), '2 d ago');
});

test('formatRelative reads a future time as just now and handles gaps', () => {
  assert.equal(formatRelative('2026-11-22T12:05:00Z', now), 'just now');
  assert.equal(formatRelative(null, now), 'never');
  assert.equal(formatRelative('not a date', now), 'unknown');
});

test('a date with no time keeps its day whatever the zone', () => {
  assert.equal(formatDate('2026-11-22'), '22 Nov 2026');
  assert.equal(formatDate('2026-01-01'), '1 Jan 2026');
});

test('a counter is grouped and a runaway one is named in words', () => {
  assert.equal(formatCount(0), '0');
  assert.equal(formatCount(1234), '1,234');
  assert.equal(formatCount(2_500_000), '2,500,000 (about 2.5 million)');
  assert.equal(formatCount(1_795_312_815), '1,795,312,815 (about 1.8 billion)');
  assert.equal(formatCount(Number.NaN), '');
});
