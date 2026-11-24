// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ALERT_SEVERITY, MACHINE_STATUS, STATUS, TICKET_PRIORITY, TICKET_STATUS, isStatusKey, statusInfo } from './status.ts';

test('machine statuses carry a word, a shape and a tone', () => {
  assert.deepEqual(MACHINE_STATUS.online, { word: 'Online', shape: 'circle', tone: 'success' });
  assert.deepEqual(MACHINE_STATUS.offline, { word: 'Offline', shape: 'ring', tone: 'neutral' });
  assert.equal(MACHINE_STATUS.fault.shape, 'diamond');
});

test('alert severity, ticket status and ticket priority are all present', () => {
  assert.deepEqual(Object.keys(ALERT_SEVERITY), ['info', 'warning', 'critical']);
  assert.deepEqual(Object.keys(TICKET_STATUS), ['open', 'in_progress', 'closed']);
  assert.deepEqual(Object.keys(TICKET_PRIORITY), ['critical', 'high', 'medium', 'low']);
  assert.equal(statusInfo('in_progress').word, 'In progress');
});

test('a state never relies on tone alone: every entry has a word and a shape', () => {
  for (const [key, info] of Object.entries(STATUS)) {
    assert.ok(info.word.length > 0, key);
    assert.ok(['circle', 'ring', 'triangle', 'diamond', 'square'].includes(info.shape), key);
  }
});

test('critical severity and a machine fault share a shape and a tone', () => {
  assert.equal(STATUS.critical.shape, STATUS.fault.shape);
  assert.equal(STATUS.critical.tone, 'critical');
});

test('an unknown or missing value reads Unknown', () => {
  assert.equal(statusInfo('mystery').word, 'Unknown');
  assert.equal(statusInfo(null).word, 'Unknown');
  assert.equal(isStatusKey('online'), true);
  assert.equal(isStatusKey('toString'), false);
});
