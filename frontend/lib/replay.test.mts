import { test } from 'node:test';
import assert from 'node:assert/strict';
import { replayView } from './replay.ts';

test('a protected machine says so and keeps the API sentence as it came', () => {
  const v = replayView({ replay_protected: true, replay_status: 'protected: every post must carry a newer boot and seq', last_boot: 7, last_seq: 1042 }, true);
  assert.equal(v.label, 'Protected');
  assert.equal(v.status, 'protected: every post must carry a newer boot and seq');
  assert.equal(v.lastPair, 'boot 7, seq 1042');
  assert.equal(v.canAccept, true);
  assert.equal(v.lockedOut, false);
});

test('a machine that does not send the pair is not protected and has no accept action', () => {
  const v = replayView({ replay_protected: false, replay_status: 'no replay protection: this machine does not send boot and seq' }, true);
  assert.equal(v.label, 'Not protected');
  assert.equal(v.canAccept, false);
  assert.equal(v.lastPair, null);
});

test('only an admin gets the accept action', () => {
  assert.equal(replayView({ replay_protected: true }, false).canAccept, false);
});

test('three refusals in a row lock the machine out', () => {
  assert.equal(replayView({ replay_protected: true, replay_refused: 2 }, true).lockedOut, false);
  const v = replayView({ replay_protected: true, replay_refused: 3, replay_refused_at: '2026-11-22T10:00:00Z' }, true);
  assert.equal(v.lockedOut, true);
  assert.equal(v.refusedAt, '2026-11-22T10:00:00Z');
});

test('a counter jump puts the key at risk and keeps the API warning and advice verbatim', () => {
  const v = replayView({ replay_protected: true, counter_jump_note: 'seq rose by 2000000', replay_warning: "The counter rose too fast: seq rose by 2000000. Rotate this machine's key", replay_recovery: 'Accepting a new counter lets this machine post again. Rotate the key as well' }, true);
  assert.equal(v.keyAtRisk, true);
  assert.equal(v.warning, "The counter rose too fast: seq rose by 2000000. Rotate this machine's key");
  assert.match(v.recovery ?? '', /Rotate the key as well/);
});

test('an older API that sends none of the fields reads as not reported and never throws', () => {
  const v = replayView({}, true);
  assert.equal(v.label, 'Not reported');
  assert.equal(v.canAccept, false);
  assert.equal(v.keyAtRisk, false);
  assert.equal(replayView(null, false).protected, null);
});

import { endSentence } from './replay.ts';

test('a sentence from the API gets one full stop and no more', () => {
  assert.equal(endSentence("Rotate this machine's key"), "Rotate this machine's key.");
  assert.equal(endSentence('Already done.'), 'Already done.');
});
