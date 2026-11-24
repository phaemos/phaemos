import { test } from 'node:test';
import assert from 'node:assert/strict';
import { limitSentence, limitsReached, nextUtcMidnight, resumeWords } from './notificationLimit.ts';

const NOW = Date.parse('2026-11-22T14:00:00Z');
const entry = (resource: string, created_at: string, cap = 50) => ({ action: 'alert_cap_reached', resource, created_at, detail: `${resource} alerts paused until 00:00 UTC: the daily limit of ${cap} was reached` });

test('the next UTC midnight is the start of tomorrow', () => {
  assert.equal(nextUtcMidnight(NOW), '2026-11-23T00:00:00.000Z');
  assert.equal(nextUtcMidnight(Date.parse('2026-12-31T23:59:59Z')), '2027-01-01T00:00:00.000Z');
});

test('a limit reached today is in force until midnight UTC', () => {
  const l = limitsReached([entry('email', '2026-11-22T09:30:00Z', 50)], NOW);
  assert.deepEqual(l, [{ channel: 'email', cap: 50, resumesAt: '2026-11-23T00:00:00.000Z' }]);
});

test('yesterday\'s entry has ended and so is not shown', () => {
  assert.deepEqual(limitsReached([entry('email', '2026-11-21T09:30:00Z')], NOW), []);
});

test('other audit entries, bad dates and an empty log show nothing', () => {
  assert.deepEqual(limitsReached([{ action: 'login', created_at: '2026-11-22T09:00:00Z' }, { action: 'alert_cap_reached', created_at: 'nope' }, { action: 'alert_cap_reached' }], NOW), []);
  assert.deepEqual(limitsReached(null, NOW), []);
  assert.deepEqual(limitsReached([], NOW), []);
});

test('both channels are named once each', () => {
  const l = limitsReached([entry('sms', '2026-11-22T10:00:00Z', 20), entry('email', '2026-11-22T09:00:00Z'), entry('email', '2026-11-22T11:00:00Z')], NOW);
  assert.deepEqual(l.map((x) => x.channel).sort(), ['email', 'text message']);
});

test('the sentence says alerts are still recorded and until when', () => {
  const one = limitSentence([{ channel: 'email', cap: 50, resumesAt: 'x' }], '00:00 UTC on 23 Nov 2026');
  assert.equal(one, 'The daily email limit was reached. Alerts are still recorded and shown here, but email messages have stopped until 00:00 UTC on 23 Nov 2026.');
  assert.match(limitSentence([{ channel: 'email', cap: 1, resumesAt: 'x' }, { channel: 'text message', cap: 1, resumesAt: 'x' }], 'tomorrow'), /email and text message limits/);
});

test('the time messages start again names the zone', () => {
  assert.equal(resumeWords('2026-11-23T00:00:00.000Z'), '00:00 UTC on 23 Nov 2026');
  assert.equal(resumeWords('nope'), '00:00 UTC');
});

import { limitsFromMetrics } from './notificationLimit.ts';

test('the limits come from the metrics route and only a reached one counts', () => {
  const l = limitsFromMetrics({ email: { limit: 50, count: 50, reached: true, resets_at: '2026-11-23T00:00:00Z' }, sms: { limit: 20, count: 3, reached: false, resets_at: '2026-11-23T00:00:00Z' } });
  assert.deepEqual(l, [{ channel: 'email', cap: 50, resumesAt: '2026-11-23T00:00:00Z' }]);
  assert.deepEqual(limitsFromMetrics(undefined), []);
  assert.deepEqual(limitsFromMetrics({ email: null as never }), []);
});
