// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  alertsGap, countFleet, currentReading, durationWords, failingFaults, faultLabel, faultSince, faultWords, faultedFields, faultsOf, fleetBucket, fleetSentence, fleetWord,
  faultedFieldsNow, knownFaultStates, knownSensorKeys, partialStateEntries, stateFields, lastPostWords, linkOf, mostRecentlyPosted, machineStatus, memoryWords, resetReasonWords, sensorFields, sensorName, signalWords, silenceSeconds, supplyWords,
} from './machineState.ts';

const NOW = Date.parse('2026-11-22T12:00:00Z');
const dev = (over: Record<string, unknown> = {}) => ({ id: 'a', name: 'Pump', status: 'online', link_state: 'online', seconds_since_last_post: 3, last_seen: '2026-11-22T11:59:57Z', health: null, ...over });
const alert = (over: Record<string, unknown> = {}) => ({ device_id: 'a', severity: 'warning', category: 'machine', resolved: false, ...over });

test('the link comes from link_state', () => {
  assert.equal(linkOf(dev(), NOW), 'online');
  assert.equal(linkOf(dev({ link_state: 'late' }), NOW), 'late');
  assert.equal(linkOf(dev({ link_state: 'offline', status: 'offline' }), NOW), 'offline');
});

test('an older API with no link_state never shows an old reading as online', () => {
  const old = { id: 'a', status: 'online', last_seen: '2026-11-21T20:00:00Z' };
  assert.equal(linkOf(old, NOW), 'offline');
  assert.equal(linkOf({ id: 'a', status: 'online', last_seen: '2026-11-22T11:59:30Z' }, NOW), 'late');
  assert.equal(linkOf({ id: 'a', status: 'online', last_seen: '2026-11-22T11:59:55Z' }, NOW), 'online');
  assert.equal(linkOf({ id: 'a', status: 'online', last_seen: null }, NOW), 'offline');
  assert.equal(linkOf({ id: 'a', status: 'offline' }, NOW), 'offline');
});

test('each machine is counted once, by the state its own badge shows', () => {
  const devices = [dev({ id: 'a' }), dev({ id: 'b' }), dev({ id: 'c' }), dev({ id: 'd', link_state: 'offline' }), dev({ id: 'e', health: { faults: { bme280: 'missing' } } })];
  const alerts = [
    alert({ device_id: 'a', severity: 'warning' }),
    alert({ device_id: 'a', severity: 'critical' }),
    alert({ device_id: 'b', severity: 'warning' }),
    alert({ device_id: 'd', severity: 'critical' }),
  ];
  assert.equal(fleetBucket(devices[0], alerts, NOW), 'fault');
  assert.equal(fleetBucket(devices[1], alerts, NOW), 'warning');
  assert.equal(fleetBucket(devices[2], alerts, NOW), 'healthy');
  assert.equal(fleetBucket(devices[3], alerts, NOW), 'unknown');
  assert.equal(fleetBucket(devices[4], alerts, NOW), 'unknown');
  assert.deepEqual(countFleet(devices, alerts, NOW), { healthy: 1, warning: 1, fault: 1, unknown: 2 });
  // the bar and every badge agree machine by machine
  for (const d of devices) assert.equal(fleetBucket(d, alerts, NOW), machineStatus(d, alerts, NOW).state);
});

test('resolved alerts and monitoring alerts do not make a machine worse', () => {
  const alerts = [alert({ resolved: true, severity: 'critical' }), alert({ category: 'monitoring', severity: 'warning' })];
  assert.equal(fleetBucket(dev(), alerts, NOW), 'healthy');
});

test('the fleet word and the bar come from one split and cannot disagree', () => {
  assert.equal(fleetWord({ healthy: 2, warning: 0, fault: 0, unknown: 0 }).word, 'Healthy');
  assert.equal(fleetWord({ healthy: 1, warning: 1, fault: 0, unknown: 0 }).word, 'Degraded');
  assert.equal(fleetWord({ healthy: 2, warning: 0, fault: 0, unknown: 1 }).word, 'Degraded');
  assert.equal(fleetWord({ healthy: 0, warning: 1, fault: 1, unknown: 0 }).word, 'Critical');
  assert.equal(fleetWord({ healthy: 0, warning: 0, fault: 0, unknown: 2 }).word, 'Unknown');
  assert.equal(fleetWord({ healthy: 0, warning: 0, fault: 0, unknown: 0 }).word, 'No machines');
  assert.equal(fleetSentence({ healthy: 1, warning: 1, fault: 0, unknown: 0 }), '1 of 2 machines healthy');
  assert.equal(fleetSentence({ healthy: 1, warning: 0, fault: 0, unknown: 1 }), '1 of 2 machines healthy, 1 unknown');
  assert.equal(fleetSentence({ healthy: 1, warning: 0, fault: 0, unknown: 0 }), '1 of 1 machine healthy');
  assert.equal(fleetSentence({ healthy: 0, warning: 0, fault: 0, unknown: 0 }), 'No machines yet');
});

test('a silent node is unknown with its reason in words', () => {
  const d = dev({ link_state: 'offline', seconds_since_last_post: 16 * 3600, status: 'offline' });
  assert.deepEqual(machineStatus(d, [], NOW), { state: 'unknown', reason: 'no reading for 16 h' });
  assert.deepEqual(machineStatus(dev({ link_state: 'offline', seconds_since_last_post: null, last_seen: null }), [], NOW), { state: 'unknown', reason: 'it has never reported' });
});

test('an active alert outranks an unknown sensor', () => {
  const d = dev({ health: { faults: { bme280: 'missing' }, reported_at: '2026-11-22T11:00:00Z' } });
  assert.equal(machineStatus(d, [alert({ severity: 'critical' })], NOW).state, 'fault');
  assert.equal(machineStatus(d, [alert({ severity: 'warning' })], NOW).state, 'warning');
});

test('a faulted sensor makes the machine unknown, names the sensor and the state and gives no "since"', () => {
  const d = dev({ health: { faults: { bme280: 'missing' }, reported_at: '2026-11-22T11:02:00Z' } });
  const s = machineStatus(d, [], NOW);
  assert.equal(s.state, 'unknown');
  assert.equal(s.reason, 'air sensor not answering');
  const two = dev({ health: { faults: { bme280: 'stuck', mq2: 'missing' } } });
  assert.equal(machineStatus(two, [], NOW).reason, 'air sensor stuck on one value and 1 more');
});

test('not fitted and warming up never make a machine unknown', () => {
  assert.deepEqual(machineStatus(dev({ health: { faults: { bme280: 'not_fitted' } } }), [], NOW), { state: 'healthy' });
  assert.deepEqual(machineStatus(dev({ health: { faults: { bme280: 'warming_up' } } }), [], NOW), { state: 'healthy' });
  // a sensor an admin marked as not fitted stays quiet even when the node does not report it
  const marked = dev({ not_fitted: ['stm32_link', 'stm32_mpu6050'], health: { faults: {} } });
  assert.deepEqual(machineStatus(marked, [], NOW), { state: 'healthy' });
  assert.deepEqual(faultsOf(marked).map((f) => [f.key, f.state, f.quiet]), [['stm32_link', 'not_fitted', true], ['stm32_mpu6050', 'not_fitted', true]]);
  // but a real fault beside it still counts
  assert.equal(machineStatus(dev({ not_fitted: ['stm32_link'], health: { faults: { mq2: 'missing' } } }), [], NOW).state, 'unknown');
  assert.equal(failingFaults(marked).length, 0);
});

test('a machine with no answer from the alerts read is unknown, never healthy', () => {
  assert.deepEqual(machineStatus(dev(), [], NOW, 'the alerts could not be loaded'), { state: 'unknown', reason: 'the alerts could not be loaded' });
  // a visible active alert still shows
  assert.equal(machineStatus(dev(), [alert({ severity: 'critical' })], NOW, 'the alerts could not be loaded').state, 'fault');
  assert.equal(fleetBucket(dev(), [], NOW, 'x'), 'unknown');
  assert.equal(countFleet([dev()], [], NOW, 'x').unknown, 1);
});

test('the alerts read is incomplete when it failed, is loading or was cut off', () => {
  assert.equal(alertsGap({ data: [], error: null, total: 0 }), null);
  assert.equal(alertsGap({ data: [], error: null }), null);
  assert.equal(alertsGap({ data: null, error: 'x' }), 'the alerts could not be loaded');
  assert.equal(alertsGap({ data: null, error: null }), 'the alerts are still loading');
  assert.equal(alertsGap({ data: [], error: 'x' }), 'the alerts could not be refreshed');
  assert.equal(alertsGap({ data: new Array(100), error: null, total: 340 }), 'only 100 of 340 alerts were loaded');
});

test('a healthy machine with no faults', () => {
  assert.deepEqual(machineStatus(dev({ health: { faults: {} } }), [], NOW), { state: 'healthy' });
  assert.deepEqual(machineStatus(dev(), [], NOW), { state: 'healthy' });
});

test('every state reads in words and an unknown state keeps its raw word', () => {
  assert.equal(faultWords('out_of_range'), 'reading outside what it can measure');
  assert.equal(faultLabel('unplugged'), 'Cable unplugged');
  assert.equal(faultLabel('garbage'), 'Data arriving but corrupted');
  assert.equal(faultLabel('one_way'), 'Answers in one direction only');
  assert.equal(faultWords('unknown'), 'in a state this dashboard has no name for');
  assert.equal(faultWords('weird'), 'in a state this dashboard has no name for (weird)');
  assert.equal(faultLabel('weird'), 'Unknown state');
  assert.equal(sensorName('mq2'), 'gas sensor');
  assert.equal(sensorName('mq2', true), 'Gas sensor (MQ-2)');
  assert.equal(sensorName('supply'), '12 V supply');
  assert.equal(sensorName('stm32_link'), 'link to the vibration node');
  assert.equal(sensorName('stm32'), 'link to the vibration node');
  assert.equal(sensorName('zzz'), 'unknown sensor (zzz)');
});

test('a hostile key cannot reach the object prototype', () => {
  for (const key of ['constructor', '__proto__', 'toString', 'hasOwnProperty', 'valueOf']) {
    assert.equal(sensorName(key), `unknown sensor (${key})`);
    assert.equal(faultWords(key), `in a state this dashboard has no name for (${key})`);
    assert.deepEqual(sensorFields(key), []);
    assert.equal(faultLabel(key), 'Unknown state');
  }
  const faults = JSON.parse('{"__proto__": "missing", "constructor": "missing", "toString": "constructor"}');
  const d = dev({ health: { faults } });
  const list = faultsOf(d);
  assert.equal(list.length, 3);
  for (const f of list) assert.equal(typeof f.name, 'string');
  assert.equal(machineStatus(d, [], NOW).state, 'unknown');
  assert.equal(typeof machineStatus(d, [], NOW).reason, 'string');
  // a run of readings is found by own key only
  assert.equal(faultSince([{ recorded_at: '2026-11-22T12:00:00Z', quality: { faults: { bme280: 'missing' } } }], 'constructor'), null);
});

test('a fault stops exactly the readings of its sensor and a link stops what it carries', () => {
  const d = dev({ health: { faults: { bme280: 'missing', stm32_link: 'silent' } } });
  const fields = faultedFields(d);
  assert.equal(fields.get('temperature')?.key, 'bme280');
  assert.equal(fields.get('vib_rms_x')?.key, 'stm32_link');
  assert.equal(fields.get('fft_peak_hz')?.key, 'stm32_link');
  assert.equal(fields.has('vibration_x'), false);
  assert.equal(fields.has('nano_temp'), false);
  assert.equal(faultedFields(dev({ health: { faults: { supply: 'out_of_range' } } })).size, 0);
});

test('a fault began at the oldest reading of its unbroken run', () => {
  const rows = [
    { recorded_at: '2026-11-22T12:00:00Z', quality: { faults: { bme280: 'missing' } } },
    { recorded_at: '2026-11-22T11:59:00Z', quality: { faults: { bme280: 'missing' } } },
    { recorded_at: '2026-11-22T11:58:00Z', quality: null },
    { recorded_at: '2026-11-22T11:57:00Z', quality: { faults: { bme280: 'missing' } } },
  ];
  assert.deepEqual(faultSince(rows, 'bme280'), { at: '2026-11-22T11:59:00Z', atLeast: false });
  assert.deepEqual(faultSince(rows.slice(0, 2), 'bme280'), { at: '2026-11-22T11:59:00Z', atLeast: true });
  assert.equal(faultSince(rows, 'mq2'), null);
});

test('durations read in the largest sensible unit and never as NaN', () => {
  assert.equal(durationWords(42), '42 s');
  assert.equal(durationWords(300), '5 min');
  assert.equal(durationWords(16 * 3600), '16 h');
  assert.equal(durationWords(3 * 86400), '3 d');
  assert.equal(durationWords(Number.NaN), 'an unknown time');
  assert.equal(durationWords(Number.POSITIVE_INFINITY), 'an unknown time');
});

test('seconds and words come from the API figure, not the browser clock', () => {
  // the browser clock is 45 minutes slow: last_seen looks 45 minutes in the future, yet the API's figure rules
  const skewed = dev({ seconds_since_last_post: 1380, last_seen: '2026-11-22T12:45:00Z', link_state: 'offline' });
  assert.equal(silenceSeconds(skewed, NOW), 1380);
  assert.equal(lastPostWords(skewed, NOW), '23 min ago');
  assert.equal(machineStatus(skewed, [], NOW).reason, 'no reading for 23 min');
  assert.equal(lastPostWords(dev({ seconds_since_last_post: 2 }), NOW), 'just now');
  assert.equal(lastPostWords(dev({ seconds_since_last_post: null, last_seen: null, link_state: 'offline' }), NOW), 'Never');
  // NaN seconds fall back to last_seen
  assert.equal(silenceSeconds(dev({ seconds_since_last_post: Number.NaN, last_seen: '2026-11-22T11:59:00Z' }), NOW), 60);
  // an unrecognised link_state with null seconds still uses last_seen
  assert.equal(silenceSeconds({ id: 'a', link_state: 'weird', seconds_since_last_post: null, last_seen: '2026-11-22T11:59:00Z' }, NOW), 60);
});

test('signal strength, memory, supply and restart reasons read in words', () => {
  assert.equal(signalWords(-55), 'strong');
  assert.equal(signalWords(-70), 'fair');
  assert.equal(signalWords(-85), 'weak');
  assert.equal(memoryWords(180000), '176\u00a0KB');
  assert.equal(supplyWords(4980), '4.98 V');
  assert.equal(resetReasonWords('poweron'), 'power switched on');
  assert.equal(resetReasonWords('brownout'), 'supply voltage dropped too low');
  assert.equal(resetReasonWords('odd'), 'odd');
});

// ---- the keys and states cannot drift from the API ----

const SENSOR_MAP = readFileSync(new URL('../../backend/app/services/sensor_map.py', import.meta.url), 'utf8');

function pythonBlock(source: string, start: string): string {
  const i = source.indexOf(start);
  assert.ok(i >= 0, `${start} not found in sensor_map.py`);
  // the block ends at the first closing bracket at the start of a line
  const rest = source.slice(i);
  const end = rest.search(/\n[})]/);
  return rest.slice(0, end);
}

test('every sensor key and its fields match backend/app/services/sensor_map.py', () => {
  const block = pythonBlock(SENSOR_MAP, 'SENSOR_FIELDS');
  const entries = [...block.matchAll(/"([a-z0-9_]+)":\s*\(([^)]*)\)/g)].map((m) => ({ key: m[1], fields: [...m[2].matchAll(/"([a-z0-9_]+)"/g)].map((f) => f[1]) }));
  assert.ok(entries.length >= 17, `expected 17 keys, read ${entries.length}`);
  assert.deepEqual([...knownSensorKeys()].sort(), entries.map((e) => e.key).sort());
  for (const e of entries) assert.deepEqual([...sensorFields(e.key)].sort(), [...e.fields].sort(), `fields of ${e.key}`);
  for (const e of entries) assert.ok(!sensorName(e.key).startsWith('unknown sensor'), `${e.key} has no plain name`);
});

test('every fault state matches backend/app/services/sensor_map.py and has a name and a label', () => {
  const block = pythonBlock(SENSOR_MAP, 'FAULT_STATES');
  const states = [...block.matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
  assert.ok(states.length >= 14, `expected 14 states, read ${states.length}`);
  assert.deepEqual([...knownFaultStates()].sort(), [...states].sort());
  for (const s of states) {
    assert.ok(!faultWords(s).startsWith('in a state'), `${s} has no words`);
    assert.notEqual(faultLabel(s), 'Unknown state', `${s} has no label`);
  }
});

test('the aliases the API accepts are named', () => {
  const m = /SENSOR_ALIASES[^=]*=\s*\{([^}]*)\}/.exec(SENSOR_MAP);
  assert.ok(m);
  for (const [, from, to] of m[1].matchAll(/"([a-z0-9_]+)":\s*"([a-z0-9_]+)"/g)) assert.equal(sensorName(from), sensorName(to), `alias ${from}`);
});

test('a panel opens on the machine that posted most recently', () => {
  const list = [dev({ id: 'old', seconds_since_last_post: 18 * 3600 }), dev({ id: 'fresh', seconds_since_last_post: 8 }), dev({ id: 'never', seconds_since_last_post: null, link_state: 'offline', last_seen: null })];
  assert.equal(mostRecentlyPosted(list, NOW)?.id, 'fresh');
  assert.equal(mostRecentlyPosted([list[2], list[0]], NOW)?.id, 'old');
  assert.equal(mostRecentlyPosted([list[2]], NOW)?.id, 'never');
  assert.equal(mostRecentlyPosted([], NOW), null);
  // equal silence keeps the first, so a poll never swaps the choice
  assert.equal(mostRecentlyPosted([dev({ id: 'a', seconds_since_last_post: 5 }), dev({ id: 'b', seconds_since_last_post: 5 })], NOW)?.id, 'a');
});

test('a link state never contradicts the silence the same answer reports', () => {
  // the API still says online while 145 s have passed with a 5 s interval
  assert.equal(linkOf(dev({ link_state: 'online', seconds_since_last_post: 145, expected_interval_s: 5 }), NOW), 'offline');
  assert.equal(linkOf(dev({ link_state: 'online', seconds_since_last_post: 30, expected_interval_s: 5 }), NOW), 'late');
  assert.equal(linkOf(dev({ link_state: 'online', seconds_since_last_post: 30, expected_interval_s: 10 }), NOW), 'online');
  // the worse of the two wins, never the better
  assert.equal(linkOf(dev({ link_state: 'offline', seconds_since_last_post: 2 }), NOW), 'offline');
  assert.equal(linkOf(dev({ link_state: 'late', seconds_since_last_post: 2 }), NOW), 'late');
  assert.equal(machineStatus(dev({ link_state: 'online', seconds_since_last_post: 145 }), [], NOW).state, 'unknown');
});

test('a field reads as a value, no reading, a fault or stale from one function', () => {
  const rows = [
    { recorded_at: '2026-11-22T11:59:58Z', temperature: null, humidity: 40 },
    { recorded_at: '2026-11-22T11:59:50Z', temperature: 24.1, humidity: 41 },
  ];
  assert.equal(currentReading(rows, 'humidity', { now: NOW }).status, 'value');
  assert.equal(currentReading(rows, 'humidity', { now: NOW }).value, 40);
  // the sensor is faulted: whatever the rows hold, there is no reading and the reason says why
  const fault = { name: 'air sensor', words: 'not answering', state: 'missing' };
  const f = currentReading(rows, 'temperature', { fault, now: NOW });
  assert.deepEqual([f.status, f.value, f.reason], ['fault', null, 'air sensor not answering']);
  assert.equal(currentReading(rows, 'temperature', { fault: { ...fault, state: 'not_fitted' }, now: NOW }).reason, 'not fitted');
  // the newest value is 10 s old and three intervals of 5 s is 15 s, so it is still current
  assert.equal(currentReading(rows, 'temperature', { now: NOW }).status, 'value');
  // the same value read a minute later is stale
  const late = currentReading(rows, 'temperature', { now: NOW + 60_000 });
  assert.deepEqual([late.status, late.value], ['stale', null]);
  assert.match(late.reason ?? '', /^nothing for /);
  assert.equal(currentReading(rows, 'pressure', { now: NOW }).status, 'none');
  assert.equal(currentReading([], 'humidity', { now: NOW }).status, 'none');
  // a flag counts as a reading when it is a boolean
  assert.equal(currentReading([{ recorded_at: '2026-11-22T11:59:58Z', gas_alert: false }], 'gas_alert', { now: NOW }).value, false);
});

test('an unplugged water sensor stops the moisture level and keeps the water flag', () => {
  const d = dev({ health: { faults: { fc28: 'unplugged' } } });
  const fields = faultedFields(d);
  assert.equal(fields.has('moisture_level'), true);
  assert.equal(fields.has('water_detected'), false);
  // any other state of the same sensor stops both, as usual
  const missing = faultedFields(dev({ health: { faults: { fc28: 'missing' } } }));
  assert.equal(missing.has('moisture_level') && missing.has('water_detected'), true);
  assert.deepEqual([...stateFields('fc28', 'unplugged')], ['moisture_level']);
  assert.deepEqual([...stateFields('fc28', 'stuck')].sort(), ['moisture_level', 'water_detected']);
  // a hostile key has no fields
  assert.deepEqual([...stateFields('constructor', 'unplugged')], []);
});

test('the partial states match backend/app/services/sensor_map.py', () => {
  const m = /PARTIAL_STATE_FIELDS[^=]*=\s*\{([^}]*)\}/.exec(SENSOR_MAP);
  assert.ok(m, 'PARTIAL_STATE_FIELDS not found');
  const backend = [...m[1].matchAll(/\("([a-z0-9_]+)",\s*"([a-z_]+)"\):\s*\(([^)]*)\)/g)].map((x) => [`${x[1]}|${x[2]}`, [...x[3].matchAll(/"([a-z0-9_]+)"/g)].map((f) => f[1]).sort()]);
  assert.ok(backend.length >= 1);
  const ours = partialStateEntries().map(([k, f]) => [k, [...f].sort()]);
  assert.deepEqual(ours.sort(), backend.sort());
});

test('a sensor the firmware build does not carry reads as not fitted and never as a fault', () => {
  const d = dev({ not_fitted_by_firmware: ['stm32_link'], health: { faults: { bme280: 'missing' }, not_fitted_by_firmware: ['nano_link'] } });
  const list = faultsOf(d);
  const byKey = Object.fromEntries(list.map((f) => [f.key, f]));
  assert.equal(byKey.stm32_link.label, 'Not fitted (firmware build)');
  assert.equal(byKey.nano_link.label, 'Not fitted (firmware build)');
  assert.equal(byKey.stm32_link.quiet, true);
  assert.equal(byKey.bme280.quiet, false);
  // it never makes a machine unknown on its own
  assert.equal(machineStatus(dev({ not_fitted_by_firmware: ['stm32_link'] }), [], NOW).state, 'healthy');
  // an admin's own mark is shown as the admin's
  const both = faultsOf(dev({ not_fitted: ['stm32_link'], not_fitted_by_firmware: ['stm32_link'] }));
  assert.equal(both.find((f) => f.key === 'stm32_link')?.label, 'Not fitted');
});

test('a pushed reading decides its own faults before the next machine poll', () => {
  const stale = dev({ health: { faults: { bme280: 'missing' } } });
  // the newest reading carries a temperature: the sensor is working, whatever the older machine read says
  assert.equal(faultedFieldsNow(stale, { quality: null, temperature: 24.1 } as never).has('temperature'), false);
  // the newest reading names a fault the machine read does not know yet and its fields are null
  const f = faultedFieldsNow(dev({ health: { faults: {} } }), { quality: { faults: { fc28: 'unplugged' } }, moisture_level: null, water_detected: true } as never);
  assert.equal(f.has('moisture_level'), true);
  assert.equal(f.has('water_detected'), false);
  // not fitted stays, whatever the reading holds
  assert.equal(faultedFieldsNow(dev({ not_fitted: ['bme280'] }), { temperature: 24 } as never).has('temperature'), true);
  assert.equal(faultedFieldsNow(dev({ health: { faults: { bme280: 'missing' } } }), null).has('temperature'), true);
});

import { faultAdvice, notAppliedSensors } from './machineState.ts';

test('the server finds stuck and out of range itself and says so', () => {
  const d = { id: 'd', health: { faults: { bme280: 'missing' }, server_faults: { mpu6050: 'stuck', ds18b20: 'out_of_range' } } };
  const faults = faultsOf(d);
  const by = Object.fromEntries(faults.map((f) => [f.key, f]));
  assert.equal(by.bme280.source, 'node');
  assert.equal(by.mpu6050.source, 'server');
  assert.equal(by.mpu6050.words, 'stuck on one value');
  assert.match(by.mpu6050.advice ?? '', /frozen/);
  assert.equal(by.ds18b20.source, 'server');
  assert.match(by.ds18b20.advice ?? '', /cannot physically measure/);
});

test('a sensor both the node and the server name keeps the node state and notes the other', () => {
  const faults = faultsOf({ id: 'd', health: { faults: { mpu6050: 'missing' }, server_faults: { mpu6050: 'stuck' } } });
  assert.equal(faults.length, 1);
  assert.equal(faults[0].state, 'missing');
  assert.equal(faults[0].source, 'both');
  assert.equal(faults[0].serverState, 'stuck');
  assert.equal(faultsOf({ id: 'd', health: { faults: { mpu6050: 'stuck' }, server_faults: { mpu6050: 'stuck' } } })[0].serverState, undefined);
});

test('a server fault is a failure and makes the machine unknown like any other', () => {
  assert.equal(failingFaults({ id: 'd', health: { server_faults: { mpu6050: 'stuck' } } }).length, 1);
});

test('every state that needs a check has advice and a quiet one has none', () => {
  for (const s of ['stuck', 'out_of_range', 'missing', 'intermittent']) assert.ok(faultAdvice(s));
  assert.equal(faultAdvice('warming_up'), null);
  assert.equal(faultAdvice('not_fitted'), null);
});

test('the claims the server did not act on come from the newest reading only', () => {
  assert.deepEqual(notAppliedSensors([{ quality: { not_applied: ['bme280', 'bme280', 'mpu6050'] } }, { quality: { not_applied: ['ina219'] } }]), ['bme280', 'mpu6050']);
  assert.deepEqual(notAppliedSensors([{ quality: null }]), []);
  assert.deepEqual(notAppliedSensors([]), []);
  assert.deepEqual(notAppliedSensors([{ quality: { not_applied: { bme280: 'missing' } } }]), ['bme280']);
  assert.deepEqual(notAppliedSensors([{ quality: { not_applied: 'bme280' } }]), []);
});
