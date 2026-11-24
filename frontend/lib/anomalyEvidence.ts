// what the model's alert says about the reading, in words and the figures the small range mark draws. The server's evidence is a
// flat object (backend/app/services/anomaly_decision.py): the counts of its window and, when one sensor carried the score, that
// sensor with its latest value and either its usual range or what it should have read for the load. Every field may be missing,
// so nothing here throws on a shape it does not know. No import beyond the unit table, so the tests can load it.

import { metricLabel, metricUnit } from './alertGroups.ts';

export interface RangeEvidence {
  kind: 'range';
  sensor: string;
  value: number;
  low: number;
  high: number;
  direction: 'above' | 'below';
}

export interface DriftEvidence {
  kind: 'drift';
  sensor: string;
  value: number;
  expected: number;
  minutes: number | null;
  direction: 'above' | 'below';
}

export type SensorEvidence = RangeEvidence | DriftEvidence;

export interface ParsedEvidence {
  readings: number | null;
  overBoundary: number | null;
  median: number | null;
  windowS: number | null;
  // null when the model flagged the reading as a whole and no one sensor carried the score
  sensor: SensorEvidence | null;
}

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const count = (v: unknown): number | null => (finite(v) ? v : null);

export function parseEvidence(raw: unknown): ParsedEvidence | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const e = raw as Record<string, unknown>;
  const out: ParsedEvidence = { readings: count(e.readings), overBoundary: count(e.over_boundary), median: count(e.median), windowS: count(e.window_s), sensor: null };
  if (typeof e.sensor !== 'string' || !e.sensor || !finite(e.value)) return out;
  const direction = e.direction === 'below' ? 'below' : 'above';
  const range = Array.isArray(e.range) ? e.range : null;
  const low = range && finite(range[0]) ? range[0] : finite(e.low) ? e.low : null;
  const high = range && finite(range[1]) ? range[1] : finite(e.high) ? e.high : null;
  if (low !== null && high !== null) {
    out.sensor = { kind: 'range', sensor: e.sensor, value: e.value, low: Math.min(low, high), high: Math.max(low, high), direction };
  } else if (finite(e.expected)) {
    out.sensor = { kind: 'drift', sensor: e.sensor, value: e.value, expected: e.expected, minutes: count(e.minutes), direction };
  }
  return out;
}

// fewer decimals for bigger numbers: 1013 hPa, 38.7 degrees, 0.12 g
export function figure(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 100) return n.toFixed(0);
  if (abs >= 10) return n.toFixed(1);
  return n.toFixed(2).replace(/(\.\d)0$/, '$1');
}

function withUnit(text: string, unit: string): string {
  if (!unit) return text;
  return unit === '%' ? `${text}%` : `${text} ${unit}`;
}

// the sentence names the sensor the way the server's reason does ("current", "supply voltage")
const SENSOR_WORDS: Record<string, string> = { current_ma: 'current', power_mw: 'power', bus_voltage: 'supply voltage', ir_temperature: 'surface temperature', contact_temp: 'contact temperature' };

export function evidenceSensorWords(sensor: string): string {
  return SENSOR_WORDS[sensor] ?? metricLabel(sensor);
}

const upper = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);

// "Current is well above this machine's usual range: 14.2 mA against a usual 6.1 to 9.8 mA". "Well" is used for a critical alert, which
// the server only raises when the score has been high for a sustained window. With no sensor in the evidence the model judged the
// reading as a whole and says so.
export function evidenceWords(raw: unknown, severity?: string | null): string {
  const ev = parseEvidence(raw);
  if (!ev || !ev.sensor) return 'The model flagged the readings as a whole. No one sensor stood out.';
  const s = ev.sensor;
  const unit = metricUnit(s.sensor);
  const name = upper(evidenceSensorWords(s.sensor));
  if (s.kind === 'drift') {
    const delta = Math.abs(s.value - s.expected);
    const over = s.minutes ? ` over the last ${s.minutes} minutes` : '';
    return `${name} is ${withUnit(figure(delta), unit)} ${s.direction} what this machine normally shows for this load${over}: ${withUnit(figure(s.value), unit)} against an expected ${withUnit(figure(s.expected), unit)}`;
  }
  const how = severity === 'critical' ? 'well ' : '';
  return `${name} is ${how}${s.direction} this machine's usual range: ${withUnit(figure(s.value), unit)} against a usual ${figure(s.low)} to ${withUnit(figure(s.high), unit)}`;
}

// the window the alert was judged over: "9 of 12 scored readings were at or over the limit in the last 120 s"
export function evidenceWindowWords(raw: unknown): string | null {
  const ev = parseEvidence(raw);
  if (!ev || ev.readings === null || ev.overBoundary === null) return null;
  const secs = ev.windowS !== null ? ` in the last ${Math.round(ev.windowS)} s` : '';
  return `${ev.overBoundary} of ${ev.readings} scored readings were at or over the model's limit${secs}`;
}

export interface RangeMark {
  // positions along the track, 0 to 100
  low: number;
  high: number;
  value: number;
  direction: 'above' | 'below' | 'inside';
}

// the positions for a range mark. The track runs from a margin below the lower of the three figures to a margin above the higher, so the
// usual band and the value both always fit. The value is never clamped, because a value far outside must look far outside.
export function rangeMark(s: RangeEvidence): RangeMark {
  const lo = Math.min(s.low, s.value);
  const hi = Math.max(s.high, s.value);
  const pad = Math.max((hi - lo) * 0.15, 1e-9);
  const from = lo - pad;
  const span = hi + pad - from;
  const at = (v: number) => Math.round(((v - from) / span) * 1000) / 10;
  const direction = s.value > s.high ? 'above' : s.value < s.low ? 'below' : 'inside';
  return { low: at(s.low), high: at(s.high), value: at(s.value), direction };
}
