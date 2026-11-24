// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { alertFiltersToQuery, DEFAULT_ALERT_FILTERS, hasNarrowingFilters, parseAlertFilters } from './alertFilters.ts';

const A = '11111111-1111-4111-8111-111111111111';
const B = '22222222-2222-4222-8222-222222222222';

function params(query: string) {
  return new URLSearchParams(query);
}

test('an empty query gives the defaults', () => {
  assert.deepEqual(parseAlertFilters(params('')), DEFAULT_ALERT_FILTERS);
});

test('reads every filter', () => {
  const f = parseAlertFilters(params(`state=resolved&severity=critical&category=monitoring&machine=${A}`));
  assert.deepEqual(f, { state: 'resolved', kind: 'all', severity: 'critical', category: 'monitoring', machine: A });
});

test('an unknown value falls back to the default', () => {
  const f = parseAlertFilters(params('state=all&view=flat&severity=urgent&category=other&machine=<script>'));
  assert.deepEqual(f, DEFAULT_ALERT_FILTERS);
});

test('the query leaves out defaults and round-trips', () => {
  assert.equal(alertFiltersToQuery(DEFAULT_ALERT_FILTERS), '');
  const f = { state: 'resolved' as const, kind: 'anomaly' as const, severity: 'warning' as const, category: 'machine' as const, machine: A };
  const q = alertFiltersToQuery(f);
  assert.deepEqual(parseAlertFilters(params(q)), f);
  assert.equal(alertFiltersToQuery({ ...DEFAULT_ALERT_FILTERS, severity: 'info' }), 'severity=info');
});

test('narrowing filters are detected', () => {
  assert.equal(hasNarrowingFilters(DEFAULT_ALERT_FILTERS), false);
  assert.equal(hasNarrowingFilters({ ...DEFAULT_ALERT_FILTERS, machine: A }), true);
  assert.equal(hasNarrowingFilters({ ...DEFAULT_ALERT_FILTERS, category: 'monitoring' }), true);
  assert.equal(hasNarrowingFilters({ ...DEFAULT_ALERT_FILTERS, state: 'resolved' }), false);
});

test('the active filters are counted for the phone button', async () => {
  const { activeFilterCount } = await import('./alertFilters.ts');
  assert.equal(activeFilterCount(DEFAULT_ALERT_FILTERS), 0);
  assert.equal(activeFilterCount({ ...DEFAULT_ALERT_FILTERS, severity: 'critical', machine: A }), 2);
  assert.equal(activeFilterCount({ state: 'resolved', kind: 'rule', severity: 'info', category: 'monitoring', machine: A }), 5);
});

test('the kind filter takes the server\'s kinds only', () => {
  assert.equal(parseAlertFilters(params('kind=anomaly')).kind, 'anomaly');
  assert.equal(parseAlertFilters(params('kind=nonsense')).kind, 'all');
  assert.equal(alertFiltersToQuery({ ...DEFAULT_ALERT_FILTERS, kind: 'sensor' }), 'kind=sensor');
  assert.equal(hasNarrowingFilters({ ...DEFAULT_ALERT_FILTERS, kind: 'rule' }), true);
});
