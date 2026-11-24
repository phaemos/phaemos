import { test } from 'node:test';
import assert from 'node:assert/strict';
import { daysProblem, scopesFor, tokenState, daysUntil } from './tokenScopes.ts';

test('only an admin is offered an admin token', () => {
  assert.deepEqual(scopesFor('admin').map((s) => s.value), ['read', 'operate', 'admin']);
  for (const role of ['technician', 'viewer', null, undefined, '']) assert.deepEqual(scopesFor(role).map((s) => s.value), ['read', 'operate']);
});

test('days are a whole number from 1 to 365', () => {
  for (const ok of ['1', '90', '365', ' 30 ']) assert.equal(daysProblem(ok), null, ok);
  for (const bad of ['', '0', '366', '-1', '1.5', 'x', '1e2', '90 days']) assert.notEqual(daysProblem(bad), null, bad);
});

test('a token warns inside 14 days and is expired once its time has passed', () => {
  const now = Date.parse('2026-11-22T00:00:00Z');
  const at = (days: number) => new Date(now + days * 86_400_000).toISOString();
  assert.equal(tokenState(at(90), now), 'ok');
  assert.equal(tokenState(at(15), now), 'ok');
  assert.equal(tokenState(at(14), now), 'soon');
  assert.equal(tokenState(at(1), now), 'soon');
  assert.equal(tokenState(at(-1), now), 'expired');
  assert.equal(daysUntil(at(3), now), 3);
});
