import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseRetryAfter, retryAfterOf, waitPhrase } from './retryAfter.ts';

test('a number of seconds and an HTTP date are both read', () => {
  assert.equal(parseRetryAfter('30'), 30);
  assert.equal(parseRetryAfter(' 120 '), 120);
  assert.equal(parseRetryAfter(10), 10);
  const now = Date.parse('2026-11-22T10:00:00Z');
  assert.equal(parseRetryAfter('Sun, 22 Nov 2026 10:00:45 GMT', now), 45);
  assert.equal(parseRetryAfter('Sun, 22 Nov 2026 09:00:00 GMT', now), null);
});

test('nonsense gives nothing and a huge wait is capped at a day', () => {
  for (const bad of [undefined, null, '', 'soon', '-5', '1.5', 'NaN']) assert.equal(parseRetryAfter(bad), null, String(bad));
  assert.equal(parseRetryAfter('999999999'), 86_400);
});

test('only a 429 carries a wait', () => {
  assert.equal(retryAfterOf({ response: { status: 429, headers: { 'retry-after': '30' } } }), 30);
  assert.equal(retryAfterOf({ response: { status: 429, headers: {} } }), null);
  assert.equal(retryAfterOf({ response: { status: 400, headers: { 'retry-after': '30' } } }), null);
  assert.equal(retryAfterOf(null), null);
});

test('the wait is said in words and rounded up', () => {
  assert.equal(waitPhrase(1), '1 second');
  assert.equal(waitPhrase(30), '30 seconds');
  assert.equal(waitPhrase(59.2), '1 minute');
  assert.equal(waitPhrase(59), '59 seconds');
  assert.equal(waitPhrase(60), '1 minute');
  assert.equal(waitPhrase(61), '2 minutes');
  assert.equal(waitPhrase(3600), '1 hour');
});
