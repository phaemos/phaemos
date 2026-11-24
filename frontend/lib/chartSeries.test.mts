// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { breakAtGaps, chooseTimeTicks, decimateSeries, dedupeTicks, findGaps, gapThresholdMs, median, spanWords } from './chartSeries.ts';

const T0 = Date.parse('2026-11-22T03:00:00Z');
const s = (n: number) => T0 + n * 1000;

test('the gap threshold is three expected intervals or three median steps', () => {
  assert.equal(gapThresholdMs([], 5000), 15_000);
  assert.equal(gapThresholdMs([s(0), s(5), s(10), s(15)], null), 15_000);
  assert.equal(gapThresholdMs([s(0), s(10), s(20)], null), 30_000);
  assert.equal(gapThresholdMs([s(0)], null), 15_000);
  assert.equal(median([3, 1, 2]), 2);
});

test('a silence is found at the start, in the middle and at the end', () => {
  const win = { start: s(0), end: s(3600) };
  // readings from 600 s to 610 s, then 1600 s to 1610 s: silent before, between and after
  const times = [s(600), s(605), s(610), s(1600), s(1605), s(1610)];
  const gaps = findGaps(times, win, 15_000);
  assert.deepEqual(gaps, [{ from: s(0), to: s(600) }, { from: s(610), to: s(1600) }, { from: s(1610), to: s(3600) }]);
  // a window that is full has no gap
  assert.deepEqual(findGaps([s(0), s(5), s(10)], { start: s(0), end: s(12) }, 15_000), []);
  // a field that never had a value is silent for the whole window
  assert.deepEqual(findGaps([], win, 15_000), [{ from: s(0), to: s(3600) }]);
});

test('a gap leaves a marker row so the line is broken', () => {
  const rows = [{ t: s(0), v: 1 }, { t: s(5), v: 2 }, { t: s(900), v: 3 }];
  const out = breakAtGaps(rows, [{ from: s(5), to: s(900) }]);
  assert.equal(out.length, 4);
  assert.equal((out[2] as { v?: number }).v, undefined);
  assert.ok(out[2].t > s(5) && out[2].t < s(900));
});

test('ticks are round times, at most the room allows and all different', () => {
  const start = s(0);
  const end = s(3600);
  const t = chooseTimeTicks(start, end, 5, 0);
  assert.ok(t.length >= 2 && t.length <= 5);
  assert.equal(new Set(t).size, t.length);
  for (const x of t) assert.equal(x % 60_000, 0);
  assert.ok(chooseTimeTicks(start, end, 12, 0).length > t.length);
  // a week of window gets whole-day-or-hour ticks
  const week = chooseTimeTicks(start, start + 7 * 86_400_000, 4, 0);
  assert.ok(week.length <= 4);
  assert.deepEqual(chooseTimeTicks(5, 5, 4, 0), []);
  // the zone moves the round times, so a quarter-hour zone still lands on the clock
  const shifted = chooseTimeTicks(start, end, 5, 5.5 * 3_600_000);
  assert.ok(shifted.every((x) => (x + 5.5 * 3_600_000) % 60_000 === 0));
});

test('spans read in words', () => {
  assert.equal(spanWords(40_000), '40 s');
  assert.equal(spanWords(16 * 60_000), '16 min');
  assert.equal(spanWords(3 * 3_600_000), '3 h');
  assert.equal(spanWords(2 * 86_400_000), '2 d');
});

test('a label that comes twice in the hour the clocks go back is kept once', () => {
  // 00:30, 01:00, 01:30 (summer time) then 01:00 and 01:30 again (winter time)
  const labels = new Map<number, string>([[1, '01:00'], [2, '01:30'], [3, '01:00'], [4, '01:30'], [5, '02:00']]);
  assert.deepEqual(dedupeTicks([1, 2, 3, 4, 5], (t) => labels.get(t) ?? ''), [1, 2, 5]);
  assert.deepEqual(dedupeTicks([], () => ''), []);
});

test('a long series is cut to its peaks and dips and keeps its ends and its gaps', () => {
  const rows = Array.from({ length: 2000 }, (_, i) => ({ t: i * 1000, v: Math.sin(i / 30) * 10, w: i === 700 ? 99 : 1 }));
  rows[700] = { ...rows[700], v: 55 };
  rows[1200] = { ...rows[1200], v: -55 };
  const out = decimateSeries(rows, 'v', 300);
  assert.ok(out.length <= 320 && out.length >= 100, `kept ${out.length}`);
  assert.equal(out[0].t, 0);
  assert.equal(out[out.length - 1].t, 1999_000);
  assert.ok(out.some((r) => r.v === 55) && out.some((r) => r.v === -55), 'the spike and the dip survive');
  assert.deepEqual(out.map((r) => r.t), [...out.map((r) => r.t)].sort((a, b) => a - b));
  // a short series is returned whole and a break stays where it was
  assert.equal(decimateSeries(rows.slice(0, 50), 'v', 300).length, 50);
  const withBreak = [...rows.slice(0, 1000), { t: 1_000_500 } as (typeof rows)[number], ...rows.slice(1000)];
  const cut = decimateSeries(withBreak, 'v', 300);
  const at = cut.findIndex((r) => r.t === 1_000_500);
  assert.ok(at > 0 && at < cut.length - 1);
  assert.equal(typeof (cut[at - 1] as { v: number }).v, 'number');
  assert.equal(typeof (cut[at + 1] as { v: number }).v, 'number');
});
