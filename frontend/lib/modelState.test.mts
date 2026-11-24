import { test } from 'node:test';
import assert from 'node:assert/strict';
import { detectionWords, falseAlertRow, fileStateWords, modelView, nightlyWords, refusalFor, retrainCounts, retrainHeadline, rowsRefusedWords } from './modelState.ts';

test('a ready machine says which model scores it', () => {
  assert.match(modelView({ state: 'ready', scope: 'machine' }).detail, /its own model/);
  assert.match(modelView({ state: 'ready', scope: 'node_type' }).detail, /node type/);
  assert.equal(modelView({ state: 'ready', scope: 'machine' }).label, 'Ready');
});

test('a machine in learning shows its hours and says it raises no anomaly alerts', () => {
  const v = modelView({ state: 'learning', hours_collected: 9.5, hours_needed: 24 });
  assert.equal(v.label, 'Learning, 9.5 hours of 24 collected');
  assert.match(v.detail, /raises no anomaly alerts/);
  assert.equal(modelView({ state: 'learning', hours_collected: 1, hours_needed: 24 }).label, 'Learning, 1 hour of 24 collected');
  assert.equal(modelView({ state: 'learning' }).label, 'Learning');
  assert.equal(modelView({ state: 'learning', hours_collected: 0, hours_needed: 24 }).label, 'Learning, 0 hours of 24 collected');
});

test('legacy and error lead to the model page', () => {
  assert.equal(modelView({ state: 'legacy' }).toModelPage, true);
  assert.equal(modelView({ state: 'error' }).status, 'fault');
});

test('no model is plain and a refused model quotes the reason and leads to the model page', () => {
  assert.equal(modelView({ state: 'none' }).kind, 'none');
  const r = modelView({ state: 'none' }, 'it has 412 training readings and needs 500');
  assert.equal(r.kind, 'refused');
  assert.match(r.detail, /412 training readings/);
  assert.equal(r.toModelPage, true);
});

test('a missing or unknown model state never throws', () => {
  assert.equal(modelView(null).kind, 'unknown');
  assert.equal(modelView(undefined).kind, 'unknown');
  assert.equal(modelView({ state: 'new_state' }).kind, 'unknown');
  assert.equal(modelView({ state: 'ready', scope: 'constructor' }).kind, 'ready');
});

const status = { last_retrain: { models: [{ key: 'machine:abc', state: 'refused', message: 'too few clean hours' }, { key: 'machine:def', state: 'ready', message: '' }, { key: 'esp32', state: 'refused', message: 'node' }] } };

test('finds the refusal for one machine only', () => {
  assert.equal(refusalFor(status, 'abc'), 'too few clean hours');
  assert.equal(refusalFor(status, 'def'), null);
  assert.equal(refusalFor(status, 'zzz'), null);
  assert.equal(refusalFor(null, 'abc'), null);
  assert.equal(refusalFor({ last_retrain: null }, 'abc'), null);
});

test('the false alert rate is compared with the budget of one', () => {
  assert.equal(falseAlertRow(0, 1).over, false);
  assert.equal(falseAlertRow(0, 1).words, '0 false alerts a week against a budget of 1');
  assert.equal(falseAlertRow(3.2, 1).over, true);
  assert.equal(falseAlertRow(3.2, 1).words, '3.2 false alerts a week against a budget of 1');
  assert.equal(falseAlertRow(1, 1).over, false);
  assert.match(falseAlertRow(null, undefined).words, /^Not measured/);
  assert.equal(falseAlertRow(0.5, 0).budget, 1);
});

test('the readings left out of training are listed biggest first', () => {
  assert.equal(rowsRefusedWords({ maintenance: 3429, sensor_fault: 1098, machine_alert: 5851, link: 32 }), 'Left out of training: 5,851 while a machine alert was open, 3,429 in a maintenance window, 1,098 with a sensor fault, 32 beside a gap in the posts.');
  assert.equal(rowsRefusedWords({}), null);
  assert.equal(rowsRefusedWords(null), null);
  assert.match(rowsRefusedWords({ odd_reason: 4 }) ?? '', /4 odd reason/);
});

test('detection is a count and a share and a trial-less model says nothing', () => {
  assert.match(detectionWords({ trials: 25, caught: 16 }) ?? '', /Found 16 of 25 faults .* \(64 per cent\)/);
  assert.equal(detectionWords({ trials: 0, caught: 0 }), null);
  assert.equal(detectionWords(null), null);
});

test('the retrain headline says whether anything was saved', () => {
  assert.match(retrainHeadline({ status: 'trained', trigger: 'nightly' }), /nightly schedule\) saved new models|by the nightly schedule saved new models/);
  assert.match(retrainHeadline({ status: 'refused', trigger: 'manual' }), /by an admin saved nothing\. The models already in service are untouched/);
  assert.equal(retrainHeadline(null), 'No retrain has run yet.');
});

test('counts the models by what the retrain made of them', () => {
  assert.deepEqual(retrainCounts({ models: [{ key: 'a', state: 'ready' }, { key: 'b', state: 'refused' }, { key: 'c', state: 'learning' }, { key: 'd', state: 'ready' }] }), { ready: 2, refused: 1, learning: 1 });
  assert.deepEqual(retrainCounts(null), { ready: 0, refused: 0, learning: 0 });
});

test('the nightly time is written with its zone once', () => {
  assert.equal(nightlyWords('04:10'), '04:10 UTC');
  assert.equal(nightlyWords('04:10 UTC'), '04:10 UTC');
  assert.equal(nightlyWords(null), null);
});

test('every state of the model file has a sentence', () => {
  for (const s of ['ok', 'none', 'legacy', 'error', 'strange']) assert.ok(fileStateWords(s).length > 10);
});

import { modelName, retrainFinished, retrainStateBadge } from './modelState.ts';

test('a model is named by its machine, its node type or as the general one', () => {
  assert.equal(modelName({ key: 'machine:6f1c', scope: 'machine', label: 'press-01' }), 'press-01');
  assert.equal(modelName({ key: 'esp32', scope: 'node_type' }), 'esp32 node type');
  assert.equal(modelName({ key: 'general' }), 'General model');
  assert.equal(modelName({ key: 'machine:6f1c' }), 'machine 6f1c');
});

test('each retrain state has a word and a shape key', () => {
  assert.deepEqual(retrainStateBadge('refused'), { label: 'Refused', status: 'warning' });
  assert.equal(retrainStateBadge('ready').label, 'Accepted');
  assert.equal(retrainStateBadge(undefined).label, 'Unknown');
});

test('a retrain has finished only when its result is newer than the request and the page\'s earlier result', () => {
  const asked = Date.parse('2026-11-22T12:00:00Z');
  assert.equal(retrainFinished('2026-11-22T04:10:07Z', '2026-11-22T04:10:07Z', asked), false);
  assert.equal(retrainFinished('2026-11-22T04:10:07Z', null, asked), false);
  assert.equal(retrainFinished('2026-11-22T12:00:30Z', '2026-11-22T04:10:07Z', asked), true);
  assert.equal(retrainFinished(null, null, asked), false);
  assert.equal(retrainFinished('junk', null, asked), false);
});

test('the device\'s own refusal makes a no-model machine refused without the status route', () => {
  const v = modelView({ state: 'none', refusal: 'too few clean hours' });
  assert.equal(v.kind, 'refused');
  assert.match(v.detail, /too few clean hours/);
  assert.equal(modelView({ state: 'none', refusal: 'own' }, 'from status').detail.includes('own'), true);
  assert.equal(modelView({ state: 'ready', refusal: null }).kind, 'ready');
});
