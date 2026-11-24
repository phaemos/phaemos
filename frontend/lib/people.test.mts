import { test } from 'node:test';
import assert from 'node:assert/strict';
import { actionsFor, activeAdminCount, type Person } from './people.ts';

const p = (id: string, role: Person['role'], extra: Partial<Person> = {}): Person => ({ id, name: id, email: `${id}@example.com`, role, ...extra });
const state = (list: ReturnType<typeof actionsFor>, action: string) => list.find((a) => a.action === action)!;

test('an admin cannot deactivate, demote or remove their own account', () => {
  const people = [p('me', 'admin'), p('b', 'admin')];
  const mine = actionsFor(people[0], 'me', people);
  for (const a of ['role', 'deactivate', 'remove']) {
    assert.equal(state(mine, a).enabled, false, a);
    assert.match(state(mine, a).reason ?? '', /own account/);
  }
  assert.equal(state(mine, 'reset-link').enabled, true);
});

test('the only active admin cannot be demoted, deactivated or removed', () => {
  const people = [p('me', 'admin'), p('a', 'admin'), p('t', 'technician')];
  // a is the other admin and is the last active one when me is deactivated
  const withInactive = [p('me', 'admin', { is_active: false }), p('a', 'admin')];
  const a = actionsFor(withInactive[1], 'me', withInactive);
  for (const x of ['role', 'deactivate', 'remove']) assert.match(state(a, x).reason ?? '', /only active admin/, x);
  assert.equal(activeAdminCount(people), 2);
  assert.equal(state(actionsFor(people[1], 'me', people), 'remove').enabled, true);
});

test('a deactivated person can be reactivated and not sent a reset link', () => {
  const people = [p('me', 'admin'), p('x', 'viewer', { is_active: false })];
  const a = actionsFor(people[1], 'me', people);
  assert.equal(state(a, 'reactivate').enabled, true);
  assert.equal(a.some((s) => s.action === 'deactivate'), false);
  assert.equal(state(a, 'reset-link').enabled, false);
});

test('clearing two-step is offered only to a person who has it', () => {
  const people = [p('me', 'admin'), p('x', 'viewer', { totp_enabled: true }), p('y', 'viewer')];
  assert.equal(state(actionsFor(people[1], 'me', people), 'clear-two-step').enabled, true);
  assert.equal(state(actionsFor(people[2], 'me', people), 'clear-two-step').enabled, false);
});

test('an API that predates the fields has only active accounts', () => {
  const people = [p('me', 'admin'), p('x', 'technician')];
  assert.equal(state(actionsFor(people[1], 'me', people), 'deactivate').enabled, true);
  assert.equal(activeAdminCount(people), 1);
});

test('a service account has only the actions that mean something for it', async () => {
  const { serviceActionsFor, isService } = await import('./people.ts');
  const people = [p('me', 'admin'), p('s', 'viewer', { is_service: true })];
  const a = serviceActionsFor(people[1], people);
  assert.deepEqual(a.map((x) => x.action), ['role', 'deactivate', 'remove']);
  assert.equal(a.every((x) => x.enabled), true);
  assert.equal(isService(people[1]), true);
  assert.equal(isService(people[0]), false);
  const off = serviceActionsFor({ ...people[1], is_active: false }, people);
  assert.deepEqual(off.map((x) => x.action), ['role', 'reactivate', 'remove']);
});
