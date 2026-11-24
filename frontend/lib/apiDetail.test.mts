import { test } from 'node:test';
import assert from 'node:assert/strict';
import { apiDetail } from './apiDetail.ts';

const err = (status: number, detail: unknown) => ({ response: { status, data: { detail } } });

test('a string detail on a client error is returned', () => {
  assert.equal(apiDetail(err(400, 'Email already registered')), 'Email already registered');
});

test('a validation list is joined and loses the value error prefix', () => {
  assert.equal(
    apiDetail(err(422, [{ msg: 'Value error, Phone number must be empty or in international format' }])),
    'Phone number must be empty or in international format',
  );
});

test('sign-in, permission, rate limit and server errors are left to describeApiError', () => {
  for (const s of [401, 403, 429, 500, 503]) assert.equal(apiDetail(err(s, 'x')), undefined);
});

test('anything else gives undefined', () => {
  assert.equal(apiDetail(null), undefined);
  assert.equal(apiDetail(new Error('boom')), undefined);
  assert.equal(apiDetail(err(400, '  ')), undefined);
});
