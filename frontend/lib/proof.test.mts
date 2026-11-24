import { test } from 'node:test';
import assert from 'node:assert/strict';
import { carriesProof } from './proof.ts';

test('a request with a password or a code is a proof', () => {
  assert.equal(carriesProof(JSON.stringify({ password: 'x' })), true);
  assert.equal(carriesProof({ code: '123456', password: 'x' }), true);
  assert.equal(carriesProof({ email: 'a@b.c', current_password: 'x' }), true);
  assert.equal(carriesProof({ old_password: 'a', new_password: 'b' }), true);
  assert.equal(carriesProof(undefined, '/auth/2fa/confirm?code=123456'), true);
});

test('an ordinary request is not', () => {
  assert.equal(carriesProof(undefined), false);
  assert.equal(carriesProof(JSON.stringify({ name: 'x' })), false);
  assert.equal(carriesProof('not json'), false);
  assert.equal(carriesProof({ phone_number: '+4477' }), false);
});
