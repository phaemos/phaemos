// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  aggregateFor,
  peakOverrides,
  axisLabel,
  bucketForRange,
  bucketLabel,
  bucketTooltip,
  chartCaption,
  chooseTicks,
  maxTicksFor,
  tickLabel,
  tickStyle,
  pointsForRange,
  pollIntervalMs,
  type Range,
} from './telemetryRange.ts';

const RANGES: Range[] = ['1h', '6h', '24h', '7d'];

test('the shortest range is raw and the others are bucketed', () => {
  assert.equal(bucketForRange('1h'), null);
  assert.equal(bucketForRange('6h'), 60);
  assert.equal(bucketForRange('24h'), 300);
  assert.equal(bucketForRange('7d'), 1800);
});

test('every bucketed range draws under 400 points and inside the API cap of 1000', () => {
  for (const r of RANGES) {
    if (bucketForRange(r) === null) continue;
    assert.ok(pointsForRange(r) < 400, `${r} gives ${pointsForRange(r)} points`);
    assert.ok(pointsForRange(r) <= 1000);
  }
  assert.equal(pointsForRange('6h'), 361);
  assert.equal(pointsForRange('24h'), 289);
  assert.equal(pointsForRange('7d'), 337);
});

test('every bucket is at least the API minimum of 10 seconds and at most a day', () => {
  for (const r of RANGES) {
    const b = bucketForRange(r);
    if (b !== null) assert.ok(b >= 10 && b <= 86_400);
  }
});

test('raw polls every 5 seconds and bucketed ranges poll more slowly', () => {
  assert.equal(pollIntervalMs(null), 5000);
  assert.equal(pollIntervalMs(60), 30_000);
  assert.equal(pollIntervalMs(300), 50_000);
  assert.equal(pollIntervalMs(1800), 300_000);
});

test('a bucket width reads as an adjective', () => {
  assert.equal(bucketLabel(30), '30 second');
  assert.equal(bucketLabel(60), '1 minute');
  assert.equal(bucketLabel(300), '5 minute');
  assert.equal(bucketLabel(1800), '30 minute');
  assert.equal(bucketLabel(7200), '2 hour');
});

test('each column is drawn by the aggregate the API chose for it', () => {
  assert.equal(aggregateFor('anomaly_score'), 'max');
  assert.equal(aggregateFor('vib_magnitude'), 'max');
  assert.equal(aggregateFor('vibration_x'), 'peak');
  assert.equal(aggregateFor('gyro_z'), 'peak');
  assert.equal(aggregateFor('fft_peak_hz'), 'strongest');
  assert.equal(aggregateFor('temperature'), 'mean');
  assert.equal(aggregateFor('shaft_angle'), 'mean');
});

test('the tooltip says what the value is and how many readings it comes from', () => {
  assert.equal(bucketTooltip('temperature', 60), 'Average from 60 readings in this interval');
  assert.equal(bucketTooltip('temperature', 1), 'Average from 1 reading in this interval');
  assert.equal(bucketTooltip('anomaly_score', 58), 'Highest value, from 58 readings in this interval');
  assert.equal(bucketTooltip('vibration_y', 12), 'Largest absolute value, from 12 readings in this interval');
  assert.equal(bucketTooltip('fft_peak_hz', 12), 'Frequency at the strongest vibration, from 12 readings in this interval');
});

test('a bucketed row is drawn with each signed axis as its peak', () => {
  const out = peakOverrides({ vibration_x: -1, vibration_x_peak: 3, gyro_z: 0.1, gyro_z_peak: null, temperature: 20 });
  assert.deepEqual(out, { vibration_x: 3, gyro_z: null });
  assert.deepEqual(peakOverrides({ temperature: 20 }), {});
});

test('a bucketed caption says what is drawn and the window it covers', () => {
  const caption = chartCaption({
    range: '24h',
    bucket: 300,
    loading: false,
    count: 288,
    windowStart: new Date('2026-11-21T14:00:00Z'),
    windowEnd: new Date('2026-11-22T14:00:00Z'),
    timeZone: 'UTC',
  });
  assert.equal(caption, '5 minute averages over the last 24h, from 21 Nov 14:00 to 22 Nov 14:00');
});

test('the caption covers loading and an empty window', () => {
  const base = { range: '7d' as const, bucket: 1800, windowStart: null, windowEnd: null };
  assert.equal(chartCaption({ ...base, loading: true, count: 0 }), 'Loading readings');
  assert.equal(chartCaption({ ...base, loading: false, count: 0 }), 'No readings in the last\u00a07d');
  // a failed request is never captioned as an empty window
  assert.equal(chartCaption({ ...base, loading: false, count: 0, failed: true }), 'Readings could not be loaded');
});

test('the raw caption keeps its wording and flags a cut', () => {
  const base = {
    range: '1h' as const,
    bucket: null,
    loading: false,
    windowStart: null,
    windowEnd: null,
    oldest: '2026-11-22T13:02:00Z',
    newest: '2026-11-22T14:02:00Z',
    timeZone: 'UTC',
    now: new Date('2026-11-22T14:05:00Z'),
  };
  assert.equal(chartCaption({ ...base, count: 720 }), '720 readings in the last\u00a01h, from 13:02 to 14:02');
  assert.equal(
    chartCaption({ ...base, count: 1500, cut: true }),
    'Latest 1500 readings, from 13:02 to 14:02. The last\u00a01h holds more than the chart can fetch.',
  );
});

test('one reading reads in the singular with no range', () => {
  const base = { range: '1h' as const, bucket: null, loading: false, windowStart: null, windowEnd: null, oldest: '2026-11-22T14:02:00Z', newest: '2026-11-22T14:02:00Z', timeZone: 'UTC', now: new Date('2026-11-22T14:05:00Z') };
  assert.equal(chartCaption({ ...base, count: 1 }), '1 reading in the last\u00a01h at 14:02');
});

test('axis labels carry the date only on ranges that span days', () => {
  const iso = '2026-11-21T14:05:00Z';
  assert.equal(axisLabel(iso, '1h', 'UTC'), '14:05');
  assert.equal(axisLabel(iso, '6h', 'UTC'), '14:05');
  assert.equal(axisLabel(iso, '24h', 'UTC'), '21 Nov 14:05');
  assert.equal(axisLabel(iso, '7d', 'UTC'), '21 Nov 14:05');
});

test('the tick style follows the span the chart covers', () => {
  assert.equal(tickStyle(30_000), 'seconds');
  assert.equal(tickStyle(4 * 60_000), 'seconds');
  assert.equal(tickStyle(60 * 60_000), 'time');
  assert.equal(tickStyle(24 * 3_600_000), 'time');
  assert.equal(tickStyle(7 * 24 * 3_600_000), 'daytime');
  assert.equal(tickStyle(Number.NaN), 'seconds');
  assert.equal(tickLabel('2026-11-22T03:53:12Z', 'seconds', 'UTC'), '03:53:12');
  assert.equal(tickLabel('2026-11-22T03:53:12Z', 'time', 'UTC'), '03:53');
  assert.equal(tickLabel('2026-11-22T03:53:12Z', 'daytime', 'UTC'), '22 Nov 03:53');
  assert.equal(tickLabel('nonsense', 'time', 'UTC'), '');
});

test('ticks never repeat and never exceed the room', () => {
  // 33 readings 5 seconds apart read "03:53" thirty times in the old format
  const iso = (i: number) => new Date(Date.parse('2026-11-22T03:53:00Z') + i * 5000).toISOString();
  const minute = Array.from({ length: 33 }, (_, i) => tickLabel(iso(i), 'time', 'UTC'));
  const t = chooseTicks(minute, 6).map((i) => minute[i]);
  assert.deepEqual(t, ['03:53', '03:54', '03:55']);
  const seconds = Array.from({ length: 33 }, (_, i) => tickLabel(iso(i), 'seconds', 'UTC'));
  const s = chooseTicks(seconds, 4);
  assert.deepEqual(s, [0, 11, 21, 32]);
  assert.equal(seconds[s[0]], '03:53:00');
  assert.equal(seconds[s[3]], '03:55:40');
  for (const labels of [t, s.map((i) => seconds[i]), chooseTicks(seconds, 100).map((i) => seconds[i])]) for (let i = 1; i < labels.length; i += 1) assert.notEqual(labels[i], labels[i - 1]);
  assert.deepEqual(chooseTicks([], 4), []);
  assert.deepEqual(chooseTicks(['a', 'a', 'a'], 4), [0]);
  assert.deepEqual(chooseTicks(['a', 'b', 'c'], 1), [0]);
  // evenly spread by position, so two ticks are never squeezed together by a gap in the time
  assert.deepEqual(chooseTicks(['a', 'b', 'c', 'd', 'e', 'f', 'g'], 3), [0, 3, 6]);
});

test('the room for ticks shrinks on a phone', () => {
  assert.ok(maxTicksFor(300, 8) <= 3);
  assert.ok(maxTicksFor(1200, 8) >= 8);
  assert.equal(maxTicksFor(0, 8), 3);
  assert.ok(maxTicksFor(100, 14) >= 2);
});
