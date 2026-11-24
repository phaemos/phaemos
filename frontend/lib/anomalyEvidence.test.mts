import { test } from 'node:test';
import assert from 'node:assert/strict';
import { evidenceWords, evidenceWindowWords, parseEvidence, rangeMark } from './anomalyEvidence.ts';

const range = { readings: 12, over_boundary: 9, median: 0.91, window_s: 120, sensor: 'current_ma', value: 14.2, range: [6.1, 9.8], direction: 'above' };

test('a value outside its usual range reads in words with the figures', () => {
  assert.equal(evidenceWords(range, 'critical'), "Current is well above this machine's usual range: 14.2 mA against a usual 6.1 to 9.8 mA");
});

test('a warning does not say well', () => {
  assert.match(evidenceWords(range, 'warning'), /^Current is above this machine's usual range/);
});

test('the range may come as low and high', () => {
  const { range: _drop, ...rest } = range;
  const p = parseEvidence({ ...rest, low: 6.1, high: 9.8 });
  assert.deepEqual(p?.sensor && 'low' in p.sensor ? [p.sensor.low, p.sensor.high] : null, [6.1, 9.8]);
});

test('without a sensor the model flagged the reading as a whole', () => {
  assert.match(evidenceWords({ readings: 5, over_boundary: 4, median: 0.8, window_s: 60 }), /as a whole/);
  assert.match(evidenceWords(null), /as a whole/);
  assert.match(evidenceWords(undefined), /as a whole/);
  assert.match(evidenceWords('junk'), /as a whole/);
  assert.match(evidenceWords([1, 2]), /as a whole/);
});

test('a slow drift reads as a change against what the load should give', () => {
  const words = evidenceWords({ sensor: 'temperature', value: 41, expected: 35, minutes: 20, direction: 'above' });
  assert.match(words, /^Temperature is 6\.0 °C above what this machine normally shows for this load over the last 20 minutes/);
});

test('non-numbers in the evidence never throw', () => {
  const p = parseEvidence({ sensor: 'temperature', value: 'x', range: ['a', null] });
  assert.equal(p?.sensor, null);
  assert.equal(evidenceWindowWords({}), null);
  assert.equal(evidenceWindowWords(range), "9 of 12 scored readings were at or over the model's limit in the last 120 s");
});

test('the range mark keeps the usual band and the value on the track', () => {
  const m = rangeMark({ kind: 'range', sensor: 'current_ma', value: 14.2, low: 6.1, high: 9.8, direction: 'above' });
  assert.equal(m.direction, 'above');
  for (const v of [m.low, m.high, m.value]) assert.ok(v >= 0 && v <= 100);
  assert.ok(m.low < m.high && m.high < m.value);
  const inside = rangeMark({ kind: 'range', sensor: 'x', value: 8, low: 6, high: 10, direction: 'above' });
  assert.equal(inside.direction, 'inside');
  const flat = rangeMark({ kind: 'range', sensor: 'x', value: 5, low: 5, high: 5, direction: 'above' });
  assert.ok(Number.isFinite(flat.low) && Number.isFinite(flat.value));
});
