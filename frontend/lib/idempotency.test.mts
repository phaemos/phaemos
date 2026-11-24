import { test } from 'node:test';
import assert from 'node:assert/strict';
import { idempotent, newIdempotencyKey, validKey } from './idempotency.ts';

test('a key is valid and each one is different', () => {
  const a = newIdempotencyKey();
  const b = newIdempotencyKey();
  assert.ok(validKey(a));
  assert.notEqual(a, b);
});

test('a key goes in the Idempotency-Key header', () => {
  assert.deepEqual(idempotent('abcdefgh'), { headers: { 'Idempotency-Key': 'abcdefgh' } });
});

test('a key that is too short or has a space is not valid', () => {
  assert.equal(validKey('short'), false);
  assert.equal(validKey('has a space in it'), false);
});
