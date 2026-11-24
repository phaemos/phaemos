// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { SATELLITE_SENSORS, SENSORS } from './readingGroups.ts';
import { METRIC_UNIT_KEYS, countBySeverity, describeBreach, metricLabel, metricUnit, parseAlertMessage } from './alertGroups.ts';

const DEV_A = '11111111-1111-4111-8111-111111111111';

test('parses a rule message into metric, value, comparison and threshold', () => {
  const p = parseAlertMessage('temperature is 38.672 (gt 30.0) on Walk Pump 1');
  assert.deepEqual(p, { metric: 'temperature', value: 38.672, comparison: 'gt', threshold: 30, deviceName: 'Walk Pump 1' });
});

test('parses every comparison and negative numbers', () => {
  for (const c of ['gt', 'lt', 'gte', 'lte', 'eq']) {
    assert.equal(parseAlertMessage(`pressure is -4 (${c} -5.5) on A`)?.comparison, c);
  }
  assert.equal(parseAlertMessage('pressure is -4 (lt -5.5) on A')?.threshold, -5.5);
});

test('keeps a device name that contains brackets or "on"', () => {
  assert.equal(parseAlertMessage('humidity is 80 (gt 70) on Cold Room (north) on level 2')?.deviceName, 'Cold Room (north) on level 2');
});

test('parses the current anomaly message, which has a reason and no figure', () => {
  const p = parseAlertMessage("Anomaly detected on Walk Pump 1: current is well above this machine's usual range. 9 of 12 scored readings in the last 120 s were at or over the anomaly limit of 0.70 (median 0.91)");
  assert.equal(p?.metric, 'anomaly');
  assert.equal(p?.deviceName, 'Walk Pump 1');
  assert.ok(Number.isNaN(p?.value));
});

test('parses an older anomaly message', () => {
  const p = parseAlertMessage('Anomaly detected on Walk Pump 1: 3 readings in a row outside its normal range (score 0.91)');
  assert.deepEqual(p, { metric: 'anomaly', value: 0.91, comparison: null, threshold: null, deviceName: 'Walk Pump 1' });
});

test('fails soft on text it does not recognise', () => {
  assert.equal(parseAlertMessage('Pump tripped'), null);
  assert.equal(parseAlertMessage(''), null);
  assert.equal(parseAlertMessage(null), null);
  assert.equal(parseAlertMessage('temperature is hot (gt 30.0) on A'), null);
});

test('parses a rule message that carries a closing note', () => {
  const p = parseAlertMessage('temperature is 38.672 (gt 30.0) on Walk Pump 1 (resolved: back inside the limit)');
  assert.equal(p?.deviceName, 'Walk Pump 1');
  assert.equal(parseAlertMessage('temperature is 38.6 (gt 30.0) on A (closed: the rule was changed)')?.deviceName, 'A');
});

test('a message that cannot be parsed is not described', () => {
  assert.equal(describeBreach({ metric: null, latestValue: null, threshold: null, comparison: null }), null);
  assert.equal(describeBreach({ metric: 'anomaly', latestValue: Number.NaN, threshold: null, comparison: null }), null);
});

test('describes a breach in plain words', () => {
  const words = (c: string) => describeBreach({ metric: 'temperature', latestValue: 38.672, threshold: 30, comparison: c as never });
  assert.equal(words('gt'), 'Temperature 38.7\u00a0°C over 30.0\u00a0°C');
  assert.equal(words('lt'), 'Temperature 38.7\u00a0°C under 30.0\u00a0°C');
  assert.equal(words('gte'), 'Temperature 38.7\u00a0°C at or over 30.0\u00a0°C');
  assert.equal(words('lte'), 'Temperature 38.7\u00a0°C at or under 30.0\u00a0°C');
  assert.equal(words('eq'), 'Temperature 38.7\u00a0°C equal to 30.0\u00a0°C');
});

test('describes an anomaly and large readings', () => {
  assert.equal(describeBreach({ metric: 'anomaly', latestValue: 0.91, threshold: null, comparison: null }), 'Anomaly score 0.91');
  assert.equal(describeBreach({ metric: 'pressure', latestValue: 1031.4, threshold: 1020, comparison: 'gt' }), 'Pressure 1031\u00a0hPa over 1020\u00a0hPa');
});

test('counts alerts by severity', () => {
  assert.deepEqual(countBySeverity([{ severity: 'critical' }, { severity: 'warning' }, { severity: 'warning' }, { severity: null }]), { critical: 1, warning: 2, info: 1 });
});

test('turns column names into plain words', () => {
  assert.equal(metricLabel('vib_magnitude'), 'vibration');
  assert.equal(metricLabel('temperature'), 'temperature');
  assert.equal(metricLabel('some_new_metric'), 'some new metric');
  assert.equal(describeBreach({ metric: 'vib_magnitude', latestValue: 1.84, threshold: 1.5, comparison: 'gt' }), 'Vibration 1.84\u00a0g over 1.50\u00a0g');
});

test('a humidity breach joins the percent sign to the number and a hostile metric has no unit', () => {
  assert.equal(describeBreach({ metric: 'humidity', latestValue: 81.2, threshold: 75, comparison: 'gt' }), 'Humidity 81.2% over 75.0%');
  assert.equal(metricUnit('constructor'), '');
  assert.equal(typeof metricLabel('__proto__'), 'string');
  assert.equal(metricLabel('constructor'), 'constructor');
});

test('the units match the latest readings table field by field', () => {
  for (const sensor of [...SENSORS, ...SATELLITE_SENSORS]) {
    for (const f of sensor.fields) {
      if (f.kind === 'flag') continue;
      assert.equal(metricUnit(f.key), f.unit, `unit of ${f.key}`);
    }
  }
  for (const key of METRIC_UNIT_KEYS) assert.ok([...SENSORS, ...SATELLITE_SENSORS].some((s) => s.fields.some((f) => f.key === key)) || key === 'anomaly', `${key} is not a reading`);
});
