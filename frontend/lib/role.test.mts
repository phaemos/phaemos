// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { roleFromToken } from './role.ts';

const token = (payload: object) => `h.${Buffer.from(JSON.stringify(payload)).toString('base64url')}.s`;

test('reads the role claim from a URL-safe token body', () => {
  assert.equal(roleFromToken(token({ role: 'admin' })), 'admin');
  assert.equal(roleFromToken(token({ role: 'viewer', note: '>>>???' })), 'viewer');
});

test('anything else is no role', () => {
  assert.equal(roleFromToken(null), null);
  assert.equal(roleFromToken('abc'), null);
  assert.equal(roleFromToken('a.%%%.c'), null);
  assert.equal(roleFromToken(token({ role: 'root' })), null);
  assert.equal(roleFromToken(token({})), null);
});

test('a viewer cannot write and every other role or an unknown one, is offered the controls', async () => {
  const { canWrite } = await import('./role.ts');
  assert.equal(canWrite('viewer'), false);
  assert.equal(canWrite('technician'), true);
  assert.equal(canWrite('admin'), true);
  assert.equal(canWrite(null), false);
});
