import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isBacklog, lateBy, lateWords } from './backlog.ts';

test('only quality.backlog true marks a reading as late', () => {
  assert.equal(isBacklog({ quality: { backlog: true } }), true);
  assert.equal(isBacklog({ quality: { backlog: false } }), false);
  assert.equal(isBacklog({ quality: null }), false);
  assert.equal(isBacklog({}), false);
});

test('how late it was is the gap between taken and received', () => {
  const r = (got: string) => ({ quality: { backlog: true, received_at: got } });
  assert.equal(lateBy('2026-11-22T10:00:00Z', r('2026-11-22T10:00:45Z')), '45 s');
  assert.equal(lateBy('2026-11-22T10:00:00Z', r('2026-11-22T10:20:00Z')), '20 min');
  assert.equal(lateBy('2026-11-22T10:00:00Z', r('2026-11-22T15:00:00Z')), '5 h');
  assert.equal(lateBy('2026-11-22T10:00:00Z', r('2026-11-25T10:00:00Z')), '3 d');
  assert.equal(lateBy('2026-11-22T10:00:00Z', { quality: { backlog: true } }), null);
  assert.equal(lateBy('2026-11-22T10:00:00Z', r('2026-11-22T09:00:00Z')), null);
  assert.equal(lateBy('junk', r('2026-11-22T09:00:00Z')), null);
});

test('the words always say not judged', () => {
  assert.match(lateWords('2026-11-22T10:00:00Z', { quality: { backlog: true, received_at: '2026-11-22T10:20:00Z' } }), /20 min after it was taken/);
  assert.match(lateWords('2026-11-22T10:00:00Z', { quality: { backlog: true } }), /^Arrived late\. Not judged/);
});
