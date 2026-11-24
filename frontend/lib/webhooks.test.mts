import { test } from 'node:test';
import assert from 'node:assert/strict';
import { deliveryState, failedTest, formatOf, secretFromAnswer, testOutcome, testSentence } from './webhooks.ts';

const base = { enabled: true, disabled_reason: null, last_delivery_at: null, last_status: null, last_error: null, consecutive_failures: 0 };

test('a webhook that has never sent says so', () => {
  assert.equal(deliveryState(base).label, 'Nothing sent yet');
});

test('a delivery that worked says the status and carries a word', () => {
  const s = deliveryState({ ...base, last_delivery_at: '2026-11-22T10:00:00Z', last_status: 204 });
  assert.equal(s.label, 'Delivered');
  assert.match(s.detail, /answered 204/);
});

test('a failure says the reason and how many in a row', () => {
  const s = deliveryState({ ...base, last_delivery_at: '2026-11-22T10:00:00Z', last_status: 500, last_error: 'the receiver is down', consecutive_failures: 3 });
  assert.equal(s.label, 'Failing');
  assert.match(s.detail, /answered 500/);
  assert.match(s.detail, /receiver is down\./);
  assert.match(s.detail, /3 deliveries in a row/);
});

test('nothing answering is not read as a status', () => {
  const s = deliveryState({ ...base, last_delivery_at: '2026-11-22T10:00:00Z', last_error: 'timed out', consecutive_failures: 1 });
  assert.match(s.detail, /Nothing answered/);
  assert.doesNotMatch(s.detail, /in a row/);
});

test('a webhook that is off says why when the API did', () => {
  assert.equal(deliveryState({ ...base, enabled: false }).label, 'Off');
  const s = deliveryState({ ...base, enabled: false, disabled_reason: 'its address is no longer safe.' });
  assert.equal(s.label, 'Switched off');
  assert.match(s.detail, /address is no longer safe\. Switch/);
});

test('the test answer is a success only with ok true', () => {
  assert.deepEqual(testOutcome({ ok: true, status: 204, elapsed_ms: 138 }), { ok: true, status: 204, elapsedMs: 138 });
  assert.equal(testOutcome({ success: true }).ok, false);
  assert.equal(testOutcome(null).ok, false);
  assert.match(testSentence('Ops', testOutcome({ ok: true, status: 204, elapsed_ms: 138 })), /delivered in 138 ms\. The receiver answered 204/);
});

test('a failed test is read from its error body', () => {
  const err = { response: { data: { code: 'webhook_delivery_failed', errors: [{ status: 500, elapsed_ms: 312 }] } } };
  assert.deepEqual(failedTest(err), { status: 500, elapsedMs: 312 });
  assert.deepEqual(failedTest({ response: { data: { code: 'webhook_delivery_failed', errors: [{ status: null, elapsed_ms: 9 }] } } }), { status: null, elapsedMs: 9 });
  assert.equal(failedTest({ response: { data: { code: 'other' } } }), null);
});

test('the secret is taken only from a string answer and the format defaults to chat', () => {
  assert.equal(secretFromAnswer({ secret: 'whsec_x' }), 'whsec_x');
  assert.equal(secretFromAnswer({ secret: '' }), null);
  assert.equal(secretFromAnswer(undefined), null);
  assert.equal(formatOf({}), 'chat');
  assert.equal(formatOf({ format: 'json' }), 'json');
});

test('a reason that only repeats the status is left out', () => {
  const s = deliveryState({ ...base, last_delivery_at: '2026-11-22T10:00:00Z', last_status: 500, last_error: 'http 500', consecutive_failures: 1 });
  assert.equal(s.detail, 'The receiver answered 500.');
});
