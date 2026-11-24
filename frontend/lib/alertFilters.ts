// the alerts page keeps its filters in the address so a filtered view can be linked. This file turns the query
// string into a typed filter set and back. It also applies the filters. Nothing here touches the browser.

export type AlertState = 'active' | 'resolved';
export type SeverityFilter = 'all' | 'critical' | 'warning' | 'info';
// what the alert is about: the machine or how it is monitored (a silent node, a restart loop). The API filters on this.
export type CategoryFilter = 'all' | 'machine' | 'monitoring';

// what raised the alert, as the server's `kind` filter names it
export const ALERT_KINDS = ['rule', 'anomaly', 'sensor', 'offline', 'reset_loop', 'unscored', 'clipping', 'board_mismatch'] as const;
export type KindFilter = 'all' | (typeof ALERT_KINDS)[number];

export const KIND_WORDS: Record<(typeof ALERT_KINDS)[number], string> = {
  rule: 'An alert rule',
  anomaly: 'The anomaly model',
  sensor: 'A sensor fault',
  offline: 'A silent node',
  reset_loop: 'A restart loop',
  unscored: 'No scored reading',
  clipping: 'Vibration beyond the sensor\'s range',
  board_mismatch: 'Firmware for another board',
};

export interface AlertFilters {
  kind: KindFilter;
  state: AlertState;
  severity: SeverityFilter;
  category: CategoryFilter;
  // a machine id. An empty string means every machine
  machine: string;
}

export const DEFAULT_ALERT_FILTERS: AlertFilters = { state: 'active', kind: 'all', severity: 'all', category: 'all', machine: '' };

interface ParamSource {
  get(name: string): string | null;
}

const MACHINE_ID = /^[0-9a-f-]{8,64}$/i;

// an unknown or missing value falls back to the default, so a hand-edited link never breaks the page
export function parseAlertFilters(params: ParamSource): AlertFilters {
  const state = params.get('state');
  const severity = params.get('severity');
  const category = params.get('category');
  const kind = params.get('kind');
  const machine = params.get('machine')?.trim() ?? '';
  return {
    state: state === 'resolved' ? 'resolved' : 'active',
    kind: (ALERT_KINDS as readonly string[]).includes(kind ?? '') ? (kind as KindFilter) : 'all',
    severity: severity === 'critical' || severity === 'warning' || severity === 'info' ? severity : 'all',
    category: category === 'machine' || category === 'monitoring' ? category : 'all',
    machine: MACHINE_ID.test(machine) ? machine : '',
  };
}

// only the values that differ from the defaults are written, so the plain page keeps a plain address
export function alertFiltersToQuery(filters: AlertFilters): string {
  const q = new URLSearchParams();
  if (filters.state !== DEFAULT_ALERT_FILTERS.state) q.set('state', filters.state);
  if (filters.severity !== DEFAULT_ALERT_FILTERS.severity) q.set('severity', filters.severity);
  if (filters.category !== DEFAULT_ALERT_FILTERS.category) q.set('category', filters.category);
  if (filters.kind !== DEFAULT_ALERT_FILTERS.kind) q.set('kind', filters.kind);
  if (filters.machine) q.set('machine', filters.machine);
  return q.toString();
}

export function hasNarrowingFilters(filters: AlertFilters): boolean {
  return filters.severity !== 'all' || filters.category !== 'all' || filters.kind !== 'all' || filters.machine !== '';
}

// how many filters differ from their defaults, for the phone's "Filters" button
export function activeFilterCount(filters: AlertFilters): number {
  let n = 0;
  if (filters.state !== DEFAULT_ALERT_FILTERS.state) n += 1;
  if (filters.severity !== DEFAULT_ALERT_FILTERS.severity) n += 1;
  if (filters.category !== DEFAULT_ALERT_FILTERS.category) n += 1;
  if (filters.kind !== DEFAULT_ALERT_FILTERS.kind) n += 1;
  if (filters.machine !== '') n += 1;
  return n;
}
