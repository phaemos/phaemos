import { test } from 'node:test';
import assert from 'node:assert/strict';
import { tooManyAttemptsMessage, LOCKED_MESSAGE, RATE_LIMITED_MESSAGE } from './signInErrors.ts';

test('a sentence the API wrote for its own limit is shown as it is', () => {
  assert.equal(
    tooManyAttemptsMessage({ code: 'email_changes_limit', detail: 'You have changed your email too many times. Try again later' }),
    'You have changed your email too many times. Try again later',
  );
});

test('the rate limit body gives the wait message', () => {
  assert.equal(tooManyAttemptsMessage({ error: 'Rate limit exceeded: 5 per 1 minute' }), RATE_LIMITED_MESSAGE);
});

test('an unreadable body is treated as a rate limit', () => {
  assert.equal(tooManyAttemptsMessage(null), RATE_LIMITED_MESSAGE);
  assert.equal(tooManyAttemptsMessage('nope'), RATE_LIMITED_MESSAGE);
});

test('a 429 is said plainly and any other failure is nothing', async () => {
  const { lockedMessage } = await import('./signInErrors.ts');
  assert.equal(lockedMessage({ response: { status: 429, data: { code: 'rate_limited', detail: 'Rate limit exceeded: 5 per 1 minute' } } }), 'Too many attempts. Wait a minute and try again.');
  assert.equal(lockedMessage({ response: { status: 429, data: { error: 'rate limit' } } }), 'Too many attempts. Wait a minute and try again.');
  assert.equal(lockedMessage({ response: { status: 400 } }), undefined);
  assert.equal(lockedMessage(null), undefined);
});

test('an hourly limit is not called a minute and Retry-After is used when it is sent', async () => {
  const { lockedMessage } = await import('./signInErrors.ts');
  assert.equal(lockedMessage({ response: { status: 429, data: { error: 'Rate limit exceeded: 5 per 1 hour' } } }), 'Too many attempts. The limit is 5 for every hour. Try again later.');
  assert.equal(lockedMessage({ response: { status: 429, data: { error: 'Rate limit exceeded: 5 per 1 minute' } } }), 'Too many attempts. Wait a minute and try again.');
  assert.equal(lockedMessage({ response: { status: 429, data: {}, headers: { 'retry-after': '1800' } } }), 'Too many attempts. Try again in 30 minutes.');
  assert.equal(lockedMessage({ response: { status: 429, data: {}, headers: { 'retry-after': '7200' } } }), 'Too many attempts. Try again in 2 hours.');
});
