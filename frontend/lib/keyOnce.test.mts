import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CLOSED, keyFromAnswer, keyReducer, keyWarning } from './keyOnce.ts';

test('showing a key opens it uncopied', () => {
  assert.deepEqual(keyReducer(CLOSED, { type: 'show', key: 'k1' }), { phase: 'shown', key: 'k1', copied: false });
});

test('an empty key never opens the dialog', () => {
  assert.deepEqual(keyReducer(CLOSED, { type: 'show', key: '' }), CLOSED);
});

test('a close needs a confirmation and the key survives until it is given', () => {
  let s = keyReducer(CLOSED, { type: 'show', key: 'k1' });
  assert.equal(keyReducer(s, { type: 'close' }), s);
  s = keyReducer(s, { type: 'ask_close' });
  assert.equal(s.phase, 'confirming');
  assert.equal(s.key, 'k1');
  assert.deepEqual(keyReducer(s, { type: 'close' }), CLOSED);
});

test('keeping the dialog open after the question brings the key back as it was', () => {
  let s = keyReducer(CLOSED, { type: 'show', key: 'k1' });
  s = keyReducer(s, { type: 'copied' });
  s = keyReducer(s, { type: 'ask_close' });
  assert.deepEqual(keyReducer(s, { type: 'keep' }), { phase: 'shown', key: 'k1', copied: true });
});

test('once closed the key is gone from state and nothing brings it back', () => {
  const s = keyReducer(keyReducer(keyReducer(CLOSED, { type: 'show', key: 'secret' }), { type: 'ask_close' }), { type: 'close' });
  assert.equal(JSON.stringify(s).includes('secret'), false);
  assert.deepEqual(keyReducer(s, { type: 'keep' }), CLOSED);
  assert.deepEqual(keyReducer(s, { type: 'copied' }), CLOSED);
  assert.deepEqual(keyReducer(s, { type: 'ask_close' }), CLOSED);
});

test('the key is read from an answer and only from api_key', () => {
  assert.equal(keyFromAnswer({ id: 'x', api_key: 'abc' }), 'abc');
  assert.equal(keyFromAnswer({ id: 'x' }), null);
  assert.equal(keyFromAnswer({ api_key: '' }), null);
  assert.equal(keyFromAnswer({ api_key: 7 }), null);
  assert.equal(keyFromAnswer(null), null);
});

test('the warning says the key cannot be read again and, for a rotation, that the old one has stopped', () => {
  assert.match(keyWarning(false), /cannot be read again/);
  assert.match(keyWarning(true), /old key has stopped working/);
});
