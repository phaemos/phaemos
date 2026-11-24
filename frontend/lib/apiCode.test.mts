import { test } from 'node:test';
import assert from 'node:assert/strict';
import { errorInfo, proofField, shouldRenew, requestIdOf } from './apiCode.ts';

const err = (status: number, data: unknown) => ({ response: { status, data } });

test('the code, the sentence and the request id are read from the body', () => {
  assert.deepEqual(errorInfo(err(400, { code: 'proof_wrong', detail: 'That is wrong', request_id: 'abc123' })), { status: 400, code: 'proof_wrong', detail: 'That is wrong', requestId: 'abc123' });
  assert.equal(requestIdOf(err(500, { code: 'internal_error', detail: 'x', request_id: 'r1' })), 'r1');
});

test('an answer with no body, an empty body or a body that is not an object has no code', () => {
  for (const e of [null, undefined, {}, err(500, undefined), err(500, ''), err(502, '<html>'), err(400, []), err(400, { code: 5, detail: {} })]) {
    const i = errorInfo(e);
    assert.equal(i.code, undefined);
    assert.equal(i.detail, undefined);
  }
});

test('each proof code points at the field it is about', () => {
  const both = { password: true, code: true };
  assert.equal(proofField('proof_required', both), 'password');
  assert.equal(proofField('password_wrong', both), 'password');
  assert.equal(proofField('code_required', both), 'code');
  assert.equal(proofField('two_step_code_wrong', both), 'code');
  assert.equal(proofField('proof_wrong', both), 'both');
  assert.equal(proofField('proof_wrong', { password: true, code: false }), 'password');
  assert.equal(proofField('proof_wrong', { password: false, code: true }), 'code');
  assert.equal(proofField('provider_proof_required', both), 'dialog');
  assert.equal(proofField('owns_machines', both), null);
  assert.equal(proofField(undefined, both), null);
});

test('only a 401 that is an expired token is renewed', () => {
  assert.equal(shouldRenew('token_invalid'), true);
  assert.equal(shouldRenew('session_ended'), true);
  assert.equal(shouldRenew(undefined), true);
  for (const c of ['invalid_credentials', 'sign_in_again', 'refresh_missing', 'device_key_invalid']) assert.equal(shouldRenew(c), false, c);
});
