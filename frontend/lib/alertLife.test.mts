import { test } from 'node:test';
import assert from 'node:assert/strict';
import { alertFacts, applyReading, applyReadings, isModelAlert, occurrenceOf, ruleHeadline, sortAlerts, uniqueById, type LifeAlert } from './alertLife.ts';

const base: LifeAlert = {
  id: 'a1', device_id: 'd1', rule_id: 'r1', message: 'temperature is 36.1 (gt 30.0) on Walk Pump 1', severity: 'warning', category: 'machine', kind: 'rule',
  resolved: false, triggered_at: '2026-11-22T10:00:30Z', resolved_at: null, occurrences: 14, last_value: 38.7, peak_value: 41.2,
  first_seen_at: '2026-11-22T10:00:00Z', last_seen_at: '2026-11-22T10:20:00Z', still_occurring: true,
};

test('an open alert whose condition still holds is still occurring', () => {
  assert.deepEqual(occurrenceOf(base), { state: 'occurring' });
});

test('an open alert with no recent reading says when it was last seen', () => {
  assert.deepEqual(occurrenceOf({ ...base, still_occurring: false }), { state: 'last_seen', at: '2026-11-22T10:20:00Z' });
});

test('a resolved alert says it is resolved and never still occurring', () => {
  assert.deepEqual(occurrenceOf({ ...base, resolved: true, resolved_at: '2026-11-22T11:00:00Z', still_occurring: true }), { state: 'resolved', at: '2026-11-22T11:00:00Z' });
});

test('a system alert has no sighting', () => {
  assert.deepEqual(occurrenceOf({ resolved: false, last_seen_at: null, still_occurring: null }), { state: 'none' });
  assert.deepEqual(occurrenceOf({}), { state: 'none' });
});

test('the facts carry the count, the peak and the latest value with their unit', () => {
  const f = alertFacts(base);
  assert.equal(f.readings, '14 readings');
  assert.equal(f.peak, '41.2 °C');
  assert.equal(f.latest, '38.7 °C');
  assert.equal(f.peakLabel, 'Peak');
  assert.equal(alertFacts({ ...base, occurrences: 1 }).readings, '1 reading');
});

test('an alert under a limit names its extreme the lowest', () => {
  const f = alertFacts({ ...base, message: 'pressure is 990 (lt 1000) on A', peak_value: 981, last_value: 990 });
  assert.equal(f.peakLabel, 'Lowest');
  assert.equal(f.peak, '981 hPa');
});

test('the model alert shows its highest score without a unit and no latest value', () => {
  const m: LifeAlert = { ...base, rule_id: null, kind: 'anomaly', message: 'Anomaly detected on Walk Pump 1: current is above', peak_value: 0.91, last_value: null };
  assert.equal(isModelAlert(m), true);
  const f = alertFacts(m);
  assert.equal(f.peak, '0.91');
  assert.equal(f.peakLabel, 'Highest score');
  assert.equal(f.latest, null);
});

test('an older anomaly row with no kind is still the model alert', () => {
  assert.equal(isModelAlert({ kind: null, rule_id: null, category: 'machine', message: 'Anomaly detected on X: a' }), true);
  assert.equal(isModelAlert({ kind: null, rule_id: 'r', category: 'machine', message: 'temperature is 1 (gt 0) on X' }), false);
});

test('an alert from an older API with no new fields still reads', () => {
  const f = alertFacts({ id: 'o', device_id: 'd', rule_id: 'r', message: 'temperature is 36.1 (gt 30.0) on A', severity: 'warning', triggered_at: '2026-11-22T10:00:00Z' });
  assert.equal(f.readings, null);
  assert.equal(f.peak, null);
  assert.equal(ruleHeadline({ id: 'o', device_id: 'd', rule_id: 'r', message: 'temperature is 36.1 (gt 30.0) on A', severity: 'warning', triggered_at: 'x' }), 'Temperature 36.1 °C over 30.0 °C');
});

test('the headline uses the latest value, not the value at the time it was raised', () => {
  assert.equal(ruleHeadline(base), 'Temperature 38.7 °C over 30.0 °C');
});

test('sorts critical first, then the alert seen most recently', () => {
  const list = [
    { ...base, id: 'w-old', last_seen_at: '2026-11-22T08:00:00Z' },
    { ...base, id: 'w-new', last_seen_at: '2026-11-22T11:00:00Z' },
    { ...base, id: 'c-old', severity: 'critical' as const, last_seen_at: '2026-11-22T07:00:00Z' },
  ];
  assert.deepEqual(sortAlerts(list).map((a) => a.id), ['c-old', 'w-new', 'w-old']);
});

test('one row for each id however often it is listed and the later copy wins', () => {
  const rows = uniqueById([{ id: 'a', n: 1 }, { id: 'b', n: 1 }, { id: 'a', n: 2 }]);
  assert.equal(rows.length, 2);
  assert.equal(rows.find((r) => r.id === 'a')?.n, 2);
});

const reading = (id: string, at: string, temperature: number) => ({ id, device_id: 'd1', recorded_at: at, temperature });

test('a live reading that meets the condition updates the alert in place', () => {
  const next = applyReading(base, reading('t1', '2026-11-22T10:20:05Z', 44.5));
  assert.equal(next.id, 'a1');
  assert.equal(next.occurrences, 15);
  assert.equal(next.last_value, 44.5);
  assert.equal(next.peak_value, 44.5);
  assert.equal(next.last_seen_at, '2026-11-22T10:20:05Z');
});

test('a live reading never lowers a peak and never counts when it does not meet the condition', () => {
  assert.equal(applyReading(base, reading('t', '2026-11-22T10:20:05Z', 31)).peak_value, 41.2);
  assert.equal(applyReading(base, reading('t', '2026-11-22T10:20:05Z', 20)), base);
});

test('a reading the last poll already counted is not counted again', () => {
  assert.equal(applyReading(base, reading('t', '2026-11-22T10:19:00Z', 44.5)), base);
  assert.equal(applyReading(base, reading('t', '2026-11-22T10:20:00Z', 44.5)), base);
});

test('a reading for another machine, a resolved alert or the model alert changes nothing', () => {
  assert.equal(applyReading(base, { ...reading('t', '2026-11-22T10:21:00Z', 50), device_id: 'other' }), base);
  const resolved = { ...base, resolved: true };
  assert.equal(applyReading(resolved, reading('t', '2026-11-22T10:21:00Z', 50)), resolved);
  const model = { ...base, rule_id: null, kind: 'anomaly', message: 'Anomaly detected on X: y' };
  assert.equal(applyReading(model, reading('t', '2026-11-22T10:21:00Z', 50)), model);
});

test('several live readings are applied once each, oldest first and the list keeps its length', () => {
  const rows = [reading('t2', '2026-11-22T10:20:10Z', 33), reading('t1', '2026-11-22T10:20:05Z', 44)];
  const out = applyReadings([base], [...rows, rows[0]]);
  assert.equal(out.length, 1);
  assert.equal(out[0].occurrences, 16);
  assert.equal(out[0].peak_value, 44);
  assert.equal(out[0].last_value, 33);
});

test('an alert under a limit takes the lowest value as its peak', () => {
  const low: LifeAlert = { ...base, message: 'temperature is 4 (lt 5) on A', peak_value: 3, last_value: 3.5 };
  const next = applyReading(low, reading('t', '2026-11-22T10:21:00Z', 2));
  assert.equal(next.peak_value, 2);
});
