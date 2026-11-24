// the life of one alert in words. An alert now lasts as long as its condition: the API keeps one open row for a machine and a rule
// and updates it in place (docs/api-reference.md, "Rule alerts are stateful"). This turns the row's own fields into the lines a
// reader needs: when the condition first held, when the alert was raised, whether it is still occurring, how many readings met it and
// the peak and latest values with their unit. No import beyond the word tables, so the tests can load it.

import { describeBreach, metricLabel, metricUnit, parseAlertMessage, type Comparison } from './alertGroups.ts';

export interface LifeAlert {
  id: string;
  device_id: string;
  rule_id: string | null;
  message: string | null;
  severity: 'info' | 'warning' | 'critical' | null;
  category?: string | null;
  kind?: string | null;
  sensor_key?: string | null;
  resolved?: boolean;
  triggered_at: string;
  resolved_at?: string | null;
  occurrences?: number | null;
  last_value?: number | null;
  peak_value?: number | null;
  first_seen_at?: string | null;
  last_seen_at?: string | null;
  still_occurring?: boolean | null;
  evidence?: unknown;
}

// the model's alert has no rule. An older row has no kind, so the message says which it is.
export function isModelAlert(a: Pick<LifeAlert, 'kind' | 'rule_id' | 'category' | 'message'>): boolean {
  if (a.kind) return a.kind === 'anomaly';
  return a.rule_id === null && (a.category ?? 'machine') === 'machine' && /^Anomaly detected on /.test(a.message ?? '');
}

export type Occurring =
  | { state: 'occurring' }
  | { state: 'last_seen'; at: string }
  // the alert is closed, with when
  | { state: 'resolved'; at: string | null }
  // an alert the system raised has no reading to be seen in
  | { state: 'none' };

export function occurrenceOf(a: Pick<LifeAlert, 'resolved' | 'resolved_at' | 'last_seen_at' | 'still_occurring'>): Occurring {
  if (a.resolved) return { state: 'resolved', at: a.resolved_at ?? null };
  if (!a.last_seen_at) return { state: 'none' };
  if (a.still_occurring === true) return { state: 'occurring' };
  return { state: 'last_seen', at: a.last_seen_at };
}

const upper = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);

function figure(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 100) return n.toFixed(0);
  if (abs >= 10) return n.toFixed(1);
  return n.toFixed(2);
}

function withUnit(text: string, unit: string): string {
  if (!unit) return text;
  return unit === '%' ? `${text}%` : `${text} ${unit}`;
}

export interface AlertFacts {
  // "14 readings", "1 reading". Null for an alert that carries no count (the system's)
  readings: string | null;
  // "41.2 °C" or "0.91" for a model's score
  peak: string | null;
  latest: string | null;
  // what the peak and the latest are called: "Highest", "Lowest" or "Highest score"
  peakLabel: string;
  latestLabel: string;
}

// the unit comes from the metric named in the message, which is the only place a rule alert says what it watches
export function alertFacts(a: LifeAlert): AlertFacts {
  const model = isModelAlert(a);
  const parsed = model ? null : parseAlertMessage(a.message);
  const unit = parsed ? metricUnit(parsed.metric) : '';
  const show = (v: number | null | undefined) => (typeof v === 'number' && Number.isFinite(v) ? withUnit(figure(v), model ? '' : unit) : null);
  const lowest = parsed?.comparison === 'lt' || parsed?.comparison === 'lte';
  const occurrences = typeof a.occurrences === 'number' && a.occurrences >= 1 ? a.occurrences : null;
  return {
    readings: occurrences === null ? null : `${occurrences} ${occurrences === 1 ? 'reading' : 'readings'}`,
    peak: show(a.peak_value),
    latest: model ? null : show(a.last_value),
    peakLabel: model ? 'Highest score' : lowest ? 'Lowest' : 'Peak',
    latestLabel: 'Latest',
  };
}

// the headline for a rule alert: "Temperature 38.7 °C over 30.0 °C" with the latest value when the API sent one and the value in the
// message (the one at the time the alert was raised) when it did not
export function ruleHeadline(a: LifeAlert): string | null {
  const parsed = parseAlertMessage(a.message);
  if (!parsed || parsed.metric === 'anomaly') return null;
  const latest = typeof a.last_value === 'number' && Number.isFinite(a.last_value) ? a.last_value : parsed.value;
  return describeBreach({ metric: parsed.metric, latestValue: latest, threshold: parsed.threshold, comparison: parsed.comparison });
}

// the name of what the rule watches, for a heading
export function ruleMetricName(a: LifeAlert): string | null {
  const parsed = parseAlertMessage(a.message);
  return parsed && parsed.metric !== 'anomaly' ? upper(metricLabel(parsed.metric)) : null;
}

const RANK = { critical: 0, warning: 1, info: 2 } as const;
const time = (iso: string | null | undefined) => {
  const t = iso ? Date.parse(iso) : Number.NaN;
  return Number.isNaN(t) ? 0 : t;
};

// critical first, then the alert most recently seen. A list of long-lived alerts has no flood to hide, so this is the whole order.
export function sortAlerts<A extends LifeAlert>(alerts: readonly A[]): A[] {
  return [...alerts].sort((a, b) => RANK[a.severity ?? 'info'] - RANK[b.severity ?? 'info'] || time(b.last_seen_at ?? b.triggered_at) - time(a.last_seen_at ?? a.triggered_at) || time(b.triggered_at) - time(a.triggered_at));
}

// one row for each alert id, however many times the list names it. A poll and a push can overlap and a row must never be drawn twice;
// the later copy wins, because lists are built oldest first and the newest answer is last.
export function uniqueById<A extends { id: string }>(alerts: readonly A[]): A[] {
  const byId = new Map<string, A>();
  for (const a of alerts) byId.set(a.id, a);
  return [...byId.values()];
}

interface ReadingLike {
  id?: string;
  device_id: string;
  recorded_at: string;
}

function meets(value: number, comparison: Comparison, threshold: number): boolean {
  switch (comparison) {
    case 'gt': return value > threshold;
    case 'gte': return value >= threshold;
    case 'lt': return value < threshold;
    case 'lte': return value <= threshold;
    default: return value === threshold;
  }
}

// a reading that arrives over the live socket is laid onto the alert it belongs to, in place, so the count, the peak and the latest value
// move at once. It can only change an open rule alert of the same machine and only for a reading newer than the alert's last sighting,
// so a reading the last poll already counted is never counted again. The next poll replaces the alert and that is the truth.
export function applyReading<A extends LifeAlert>(alert: A, reading: ReadingLike): A {
  if (alert.resolved || alert.device_id !== reading.device_id || alert.rule_id === null || isModelAlert(alert)) return alert;
  if ((alert.category ?? 'machine') !== 'machine') return alert;
  const parsed = parseAlertMessage(alert.message);
  if (!parsed || !parsed.comparison || parsed.threshold === null) return alert;
  const value = (reading as unknown as Record<string, unknown>)[parsed.metric];
  if (typeof value !== 'number' || !Number.isFinite(value)) return alert;
  const at = time(reading.recorded_at);
  if (at === 0 || at <= time(alert.last_seen_at ?? alert.triggered_at)) return alert;
  if (!meets(value, parsed.comparison, parsed.threshold)) return alert;
  const lowest = parsed.comparison === 'lt' || parsed.comparison === 'lte';
  const peak = typeof alert.peak_value === 'number' ? (lowest ? Math.min(alert.peak_value, value) : Math.max(alert.peak_value, value)) : value;
  return { ...alert, occurrences: (alert.occurrences ?? 0) + 1, last_value: value, peak_value: peak, last_seen_at: reading.recorded_at, still_occurring: true };
}

// the readings are applied oldest first whatever order they come in, so a reading is never skipped for arriving behind a newer one
export function applyReadings<A extends LifeAlert>(alerts: readonly A[], readings: readonly ReadingLike[]): A[] {
  if (readings.length === 0) return [...alerts];
  const oldestFirst = [...readings].sort((a, b) => time(a.recorded_at) - time(b.recorded_at));
  const seen = new Set<string>();
  const fresh = oldestFirst.filter((r) => {
    if (!r.id) return true;
    if (seen.has(r.id)) return false;
    seen.add(r.id);
    return true;
  });
  return alerts.map((a) => fresh.reduce((acc, r) => applyReading(acc, r), a));
}
