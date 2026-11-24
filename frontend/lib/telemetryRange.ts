// how the live readings chart asks for each time range and how it describes what it drew.
// pure functions only, so the choice and the wording are tested without a browser.

export type Range = '1h' | '6h' | '24h' | '7d';

export const RANGE_HOURS: Record<Range, number> = { '1h': 1, '6h': 6, '24h': 24, '7d': 168 };

// the bucket in seconds for each range or null for raw readings. A node sends one reading every 5 seconds, so
// a day is about 17,000 rows. These widths keep every bucketed range at about 290 to 360 points: a line chart
// a few hundred points wide is as much as a screen can show. Each is well under the API's cap of 1000 buckets.
//   1h  raw        720 points (the live range: every reading, with WebSocket updates)
//   6h  60 s       360 points
//   24h 300 s      288 points
//   7d  1800 s     336 points
const BUCKETS: Record<Range, number | null> = { '1h': null, '6h': 60, '24h': 300, '7d': 1800 };

export function bucketForRange(range: Range): number | null {
  return BUCKETS[range];
}

// the most points a range draws: the window over the bucket, plus one for a partial bucket at the edge
export function pointsForRange(range: Range): number {
  const bucket = BUCKETS[range];
  return bucket === null ? (RANGE_HOURS[range] * 3600) / 5 : Math.ceil((RANGE_HOURS[range] * 3600) / bucket) + 1;
}

const RAW_POLL_MS = 5_000;
const MIN_BUCKET_POLL_MS = 30_000;

// raw readings refresh every 5 seconds. A bucket only changes as its readings arrive and the newest one is
// still filling, so a bucketed range refreshes about six times per bucket and never faster than every 30 seconds
export function pollIntervalMs(bucket: number | null): number {
  return bucket === null ? RAW_POLL_MS : Math.max(MIN_BUCKET_POLL_MS, (bucket * 1000) / 6);
}

// "1 minute", "5 minute", "30 minute", "2 hour": a bucket width as an adjective
export function bucketLabel(bucket: number): string {
  if (bucket < 60) return `${bucket} second`;
  if (bucket < 3600) return `${Math.round(bucket / 60)} minute`;
  return `${Math.round(bucket / 3600)} hour`;
}

// how each column is drawn from a bucket. This mirrors the API (services/telemetry_buckets.py). The six signed axes
// are drawn as their peak (the API sends it beside the mean, which is only the static offset), the anomaly score and
// vibration magnitude as their maximum, the vibration frequency as the one at the strongest vibration and the rest
// as a mean. The shaft angle is a circular mean, which still reads as an average
const PEAK_KEYS = ['vibration_x', 'vibration_y', 'vibration_z', 'gyro_x', 'gyro_y', 'gyro_z'];
const MAX_KEYS = new Set(['anomaly_score', 'vib_magnitude']);

export type Aggregate = 'mean' | 'max' | 'peak' | 'strongest';

export function aggregateFor(key: string): Aggregate {
  if (PEAK_KEYS.includes(key)) return 'peak';
  if (MAX_KEYS.has(key)) return 'max';
  return key === 'fft_peak_hz' ? 'strongest' : 'mean';
}

// the values to draw for a bucketed row: each signed axis is replaced by its peak so the chart shows the vibration
// and not the offset. Keys the row has no peak for are left out
export function peakOverrides(row: object): Record<string, number | null> {
  const fields = row as Record<string, unknown>;
  const out: Record<string, number | null> = {};
  for (const key of PEAK_KEYS) {
    const peak = fields[`${key}_peak`];
    if (typeof peak === 'number' || peak === null) out[key] = peak;
  }
  return out;
}

// the tooltip line for a bucketed point. The count is rows in the interval, not readings of this one sensor
export function bucketTooltip(key: string, count: number): string {
  const from = `from ${count} ${count === 1 ? 'reading' : 'readings'} in this interval`;
  switch (aggregateFor(key)) {
    case 'peak': return `Largest absolute value, ${from}`;
    case 'max': return `Highest value, ${from}`;
    case 'strongest': return `Frequency at the strongest vibration, ${from}`;
    default: return `Average ${from}`;
  }
}

// 14:02 for hourly and six hour ranges, 21 Nov 14:02 once the range spans days
export function axisLabel(iso: string, range: Range, timeZone?: string): string {
  const d = new Date(iso);
  const time = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone });
  if (range === '1h' || range === '6h') return time;
  return `${d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone })} ${time}`;
}

// how the time axis writes each tick, chosen from the span the chart really covers: seconds while the readings span only a
// few minutes (a tick of "03:53" repeated five times says nothing), hours and minutes up to a day and a half, then the day
// with the time
export type TickStyle = 'seconds' | 'time' | 'daytime';

const SHORT_SPAN_MS = 5 * 60_000;
const LONG_SPAN_MS = 36 * 3_600_000;

export function tickStyle(spanMs: number): TickStyle {
  if (!Number.isFinite(spanMs) || spanMs < SHORT_SPAN_MS) return 'seconds';
  return spanMs > LONG_SPAN_MS ? 'daytime' : 'time';
}

export function tickLabel(iso: string, style: TickStyle, timeZone?: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const time = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', ...(style === 'seconds' ? { second: '2-digit' as const } : {}), timeZone });
  if (style !== 'daytime') return time;
  return `${d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone })} ${time}`;
}

// the ticks to draw, as positions in the list of rows. The axis spaces rows evenly by position, so the ticks are spread evenly
// by position too (at most `max`, always the first and the last row). A tick whose text equals the one before it is dropped, so
// no two neighbours can read the same and a long run of readings inside one minute gets one tick.
export function chooseTicks(labels: readonly string[], max: number): number[] {
  const n = labels.length;
  if (n === 0) return [];
  const cap = Math.max(1, Math.floor(max));
  const wanted: number[] = [];
  if (n <= cap) for (let i = 0; i < n; i += 1) wanted.push(i);
  else if (cap === 1) wanted.push(0);
  else for (let i = 0; i < cap; i += 1) wanted.push(Math.round((i * (n - 1)) / (cap - 1)));
  const out: number[] = [];
  for (const i of wanted) {
    if (!labels[i]) continue;
    if (out.length > 0 && labels[out[out.length - 1]] === labels[i]) continue;
    out.push(i);
  }
  return out;
}

// how many ticks fit: each needs its own text width (about 7.5 px a character at 13 px) and a gap
export function maxTicksFor(plotWidth: number, labelChars: number): number {
  if (!Number.isFinite(plotWidth) || plotWidth <= 0) return 3;
  return Math.max(2, Math.floor(plotWidth / (labelChars * 7.5 + 24)));
}

// 21 Nov 14:00, always with the date so a window that crosses midnight reads without guessing
export function fullStamp(d: Date, timeZone?: string): string {
  const time = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone });
  return `${d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone })} ${time}`;
}

// 14:02 for a reading from the current day and 21 Nov 14:02 for any other day, as the raw caption always said
export function rawStamp(d: Date, now: Date, timeZone?: string): string {
  const day = (x: Date) => x.toLocaleDateString('en-GB', { timeZone });
  return day(d) === day(now) ? d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone }) : fullStamp(d, timeZone);
}

interface CaptionInput {
  range: Range;
  bucket: number | null;
  loading: boolean;
  // how many rows are drawn
  count: number;
  // the window that was asked for, so the words describe the request and not just the rows that came back
  windowStart: Date | null;
  windowEnd: Date | null;
  timeZone?: string;
  // the current time, for the raw caption's short stamps
  now?: Date;
  // raw range only: the oldest and newest drawn reading plus whether the fetch hit its row limit
  oldest?: string;
  newest?: string;
  cut?: boolean;
  // the request failed, so the caption must not read as an empty window
  failed?: boolean;
}

// the plain-words line under the chart title: it says only what is drawn
export function chartCaption(c: CaptionInput): string {
  if (c.loading) return 'Loading readings';
  if (c.failed && c.count === 0) return 'Readings could not be loaded';
  if (c.count === 0) return `No readings in the last\u00a0${c.range}`;
  if (c.bucket !== null) {
    const span = c.windowStart && c.windowEnd ? `, from ${fullStamp(c.windowStart, c.timeZone)} to ${fullStamp(c.windowEnd, c.timeZone)}` : '';
    return `${bucketLabel(c.bucket)} averages over the last ${c.range}${span}`;
  }
  const now = c.now ?? new Date();
  const from = c.oldest ? rawStamp(new Date(c.oldest), now, c.timeZone) : '';
  const to = c.newest ? rawStamp(new Date(c.newest), now, c.timeZone) : '';
  // one reading has no range to speak of: "from 02:47 to 02:47" would say nothing
  const span = c.count === 1 || from === to ? ` at ${to}` : `, from ${from} to ${to}`;
  const noun = c.count === 1 ? 'reading' : 'readings';
  return c.cut
    ? `Latest ${c.count} ${noun}${span}. The last\u00a0${c.range} holds more than the chart can fetch.`
    : `${c.count} ${noun} in the last\u00a0${c.range}${span}`;
}
