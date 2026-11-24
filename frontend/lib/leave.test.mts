import { test } from 'node:test';
import assert from 'node:assert/strict';
import { canLeaveFor } from './leave.ts';

const own = ['https://phaemos.com', 'https://dashboard.phaemos.com'];

test('a listed provider may be visited on its own host', () => {
  assert.equal(canLeaveFor('https://accounts.google.com/o/oauth2/v2/auth?client_id=x', ['google'], own), true);
  assert.equal(canLeaveFor('https://github.com/login/oauth/authorize?x=1', ['github', 'google'], own), true);
  assert.equal(canLeaveFor('https://login.microsoftonline.com/common/oauth2/v2.0/authorize', ['microsoft'], own), true);
});

test('the two own addresses are allowed', () => {
  assert.equal(canLeaveFor('https://dashboard.phaemos.com/profile?linked=google', [], own), true);
  assert.equal(canLeaveFor('https://phaemos.com/', [], own), true);
});

test('anything else is refused', () => {
  const refused = [
    'https://evil.example/', 'https://accounts.google.com.evil.example/', 'https://evil.example/accounts.google.com',
    'https://accounts.google.com@evil.example/', 'https://user:pw@accounts.google.com/', 'http://accounts.google.com/',
    'javascript:alert(1)', 'data:text/html,x', '//evil.example', '/relative', '', 'https://github.com/', 'https://phaemos.com.evil.example/',
  ];
  for (const a of refused) assert.equal(canLeaveFor(a, ['google'], own), false, a);
  // a provider the API does not list is not allowed even on its real host
  assert.equal(canLeaveFor('https://github.com/login', ['google'], own), false);
});
