// pure helpers for the time axis of a chart: where a series has gaps and which ticks the axis draws. A chart is drawn against
// real time, so a silence is as wide as it was and a gap is found from the readings that hold a value for that one field (a
// run of nulls from a faulted sensor is a gap too). No import, so the Node tests can load it.

export interface Gap {
  from: number;
  to: number;
}

export function median(values: readonly number[]): number {
  if (values.length === 0) return 0;
  const s = [...values].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

// readings further apart than three expected intervals have a gap between them. The interval is the device's own
// (expected_interval_s) or, when it is not known, the median step between the readings.
export function gapThresholdMs(times: readonly number[], expectedMs?: number | null): number {
  if (expectedMs && expectedMs > 0) return 3 * expectedMs;
  const steps: number[] = [];
  for (let i = 1; i < times.length; i += 1) steps.push(times[i] - times[i - 1]);
  const m = median(steps);
  return m > 0 ? 3 * m : 15_000;
}

// the silent spans of a window: before the first reading, between two readings and after the last one. times are ascending and
// hold only readings with a value for the field being drawn.
export function findGaps(times: readonly number[], window: { start: number; end: number }, thresholdMs: number): Gap[] {
  const out: Gap[] = [];
  if (times.length === 0) return window.end > window.start ? [{ from: window.start, to: window.end }] : [];
  if (times[0] - window.start > thresholdMs) out.push({ from: window.start, to: times[0] });
  for (let i = 1; i < times.length; i += 1) if (times[i] - times[i - 1] > thresholdMs) out.push({ from: times[i - 1], to: times[i] });
  const last = times[times.length - 1];
  if (window.end - last > thresholdMs) out.push({ from: last, to: window.end });
  return out;
}

// rows in time order with an empty marker row inside each gap, so a line chart that does not connect nulls leaves the gap open
export function breakAtGaps<T extends { t: number }>(rows: readonly T[], gaps: readonly Gap[]): (T | { t: number })[] {
  const out: (T | { t: number })[] = [...rows];
  for (const g of gaps) if (g.from > 0 && rows.some((r) => r.t === g.from)) out.push({ t: g.from + Math.max(1, Math.floor((g.to - g.from) / 2)) });
  return out.sort((a, b) => a.t - b.t);
}

const STEPS_MS = [10, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400, 172800, 259200, 604800].map((s) => s * 1000);

// ticks for a numeric time axis: round times (on the clock, in the reader's own zone through offsetMs) spread so that at most
// `max` fit. Every tick is a different time, so no two can read alike once they are written to the minute.
export function chooseTimeTicks(start: number, end: number, max: number, offsetMs: number = -new Date(start).getTimezoneOffset() * 60_000): number[] {
  if (!(end > start)) return [];
  const cap = Math.max(2, Math.floor(max));
  const step = STEPS_MS.find((s) => Math.floor((end - start) / s) + 1 <= cap) ?? STEPS_MS[STEPS_MS.length - 1];
  const first = Math.ceil((start + offsetMs) / step) * step - offsetMs;
  const out: number[] = [];
  for (let t = first; t <= end; t += step) out.push(t);
  return out;
}

// a line cannot show more points than it has pixels and a thousand-point line in a dozen charts costs a slow redraw. A run of numeric
// points is cut to its minimum and maximum in each slice of the run, in time order, so every peak and dip is kept and the first and last
// point of the run stay. Rows with no value (a gap marker or a null) break a run and are kept as they are.
export function decimateSeries<T extends { t: number }>(rows: readonly T[], key: string, maxPoints: number): T[] {
  const isNum = (r: T) => typeof (r as unknown as Record<string, unknown>)[key] === 'number';
  const numeric = rows.reduce((n, r) => n + (isNum(r) ? 1 : 0), 0);
  if (numeric <= maxPoints) return [...rows];
  const out: T[] = [];
  let i = 0;
  while (i < rows.length) {
    if (!isNum(rows[i])) {
      out.push(rows[i]);
      i += 1;
      continue;
    }
    let j = i;
    while (j < rows.length && isNum(rows[j])) j += 1;
    const run = rows.slice(i, j);
    const budget = Math.max(2, Math.floor((maxPoints * run.length) / numeric));
    if (run.length <= budget) out.push(...run);
    else {
      const bins = Math.max(1, Math.floor(budget / 2));
      const size = run.length / bins;
      const keep = new Set<number>([0, run.length - 1]);
      for (let b = 0; b < bins; b += 1) {
        const from = Math.floor(b * size);
        const to = Math.min(run.length, Math.floor((b + 1) * size));
        let lo = from;
        let hi = from;
        for (let k = from; k < to; k += 1) {
          const v = (run[k] as unknown as Record<string, number>)[key];
          if (v < (run[lo] as unknown as Record<string, number>)[key]) lo = k;
          if (v > (run[hi] as unknown as Record<string, number>)[key]) hi = k;
        }
        keep.add(lo);
        keep.add(hi);
      }
      for (const k of [...keep].sort((a, b) => a - b)) out.push(run[k]);
    }
    i = j;
  }
  return out;
}

// the ticks that read differently. In the hour the clocks go back the same clock time comes twice, so two ticks can share a label without
// being neighbours. Only the first of each label is kept, so no label appears twice on an axis.
export function dedupeTicks(ticks: readonly number[], label: (t: number) => string): number[] {
  const seen = new Set<string>();
  return ticks.filter((t) => {
    const l = label(t);
    if (seen.has(l)) return false;
    seen.add(l);
    return true;
  });
}

// "16 min" for a length of time in milliseconds, for the words that name a gap
export function spanWords(ms: number): string {
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s} s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h`;
  return `${Math.round(h / 24)} d`;
}
