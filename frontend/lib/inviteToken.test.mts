// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readInviteToken } from './inviteToken.ts';

test('the token is read from the fragment', () => {
  assert.deepEqual(readInviteToken('/accept-invite', '', '#token=abc123'), { token: 'abc123', legacyQuery: false, cleaned: '/accept-invite' });
});

test('the older query form is not accepted: it is reported and removed from the address', () => {
  assert.deepEqual(readInviteToken('/accept-invite', '?token=abc123', ''), { token: null, legacyQuery: true, cleaned: '/accept-invite' });
});

test('a token in the fragment is used even when the query also holds one', () => {
  const r = readInviteToken('/accept-invite', '?token=old', '#token=new');
  assert.equal(r.token, 'new');
  assert.equal(r.legacyQuery, true);
});

test('other query values stay in the cleaned address', () => {
  assert.deepEqual(readInviteToken('/accept-invite', '?token=abc&ref=mail', ''), { token: null, legacyQuery: true, cleaned: '/accept-invite?ref=mail' });
});

test('a url-safe token is read whole and other fragment values are ignored', () => {
  assert.equal(readInviteToken('/accept-invite', '', '#a=1&token=Ab-_9.x&b=2').token, 'Ab-_9.x');
});

test('no token gives null', () => {
  assert.deepEqual(readInviteToken('/accept-invite', '', ''), { token: null, legacyQuery: false, cleaned: '/accept-invite' });
  assert.equal(readInviteToken('/accept-invite', '?token=', '#token=').token, null);
  assert.equal(readInviteToken('/accept-invite', '?token=', '#token=').legacyQuery, false);
});
