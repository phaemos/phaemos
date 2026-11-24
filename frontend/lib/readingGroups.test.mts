// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatReadingValue, groupReadings, isRaised } from './readingGroups.ts';

const NEWER = { recorded_at: '2026-11-22T10:00:05Z', temperature: 21.46, humidity: null, vib_magnitude: 0.1234, gas_level: 120, gas_alert: false };
const OLDER = { recorded_at: '2026-11-22T10:00:00Z', temperature: 20, humidity: 41.2, pressure: 1003.4 };

test('the newest non-null value per field wins and keeps its own time', () => {
  const air = groupReadings([NEWER, OLDER], 'pico_w').find((g) => g.id === 'air')!;
  const byKey = Object.fromEntries(air.rows.map((r) => [r.key, r]));
  assert.equal(byKey.temperature.value, 21.46);
  assert.equal(byKey.temperature.at, NEWER.recorded_at);
  assert.equal(byKey.humidity.value, 41.2);
  assert.equal(byKey.humidity.at, OLDER.recorded_at);
});

test('a pico node shows only the sensors it carries', () => {
  assert.deepEqual(groupReadings([OLDER], 'pico_w').map((g) => g.id), ['air', 'light']);
});

test('a carried sensor with no reading is kept and marked missing', () => {
  const light = groupReadings([OLDER], 'pico_w').find((g) => g.id === 'light')!;
  assert.equal(light.rows[0].value, null);
  assert.equal(light.rows[0].at, null);
  assert.equal(formatReadingValue(light.rows[0]), null);
});

test('a sensor the node does not carry appears only when a reading holds a value for it', () => {
  const ids = groupReadings([NEWER], 'nano').map((g) => g.id);
  assert.ok(ids.includes('vibration'));
  assert.ok(ids.includes('gas'));
  assert.ok(!ids.includes('power'));
});

test('an unknown node type shows only what was read', () => {
  assert.deepEqual(groupReadings([OLDER], null).map((g) => g.id), ['air']);
  assert.equal(groupReadings([], 'esp32').length, 12);
});

test('values carry their unit and a flag reads as a word', () => {
  const groups = groupReadings([NEWER], 'esp32');
  const temp = groups.find((g) => g.id === 'air')!.rows[0];
  const gas = groups.find((g) => g.id === 'gas')!.rows.find((r) => r.key === 'gas_alert')!;
  // a non-breaking space between the number and its unit
  assert.equal(formatReadingValue(temp), '21.5\u00a0°C');
  assert.equal(formatReadingValue(gas), 'Clear');
  assert.equal(formatReadingValue({ ...gas, value: true }), 'Alarm');
});

test('only a flag that is on counts as raised', () => {
  const gas = groupReadings([NEWER], 'esp32').find((g) => g.id === 'gas')!.rows.find((r) => r.key === 'gas_alert')!;
  assert.equal(isRaised(gas), false);
  assert.equal(isRaised({ ...gas, value: true }), true);
  assert.equal(isRaised({ ...gas, value: null }), false);
});

test('a flag the sensor never sent reads as no reading, not as clear', () => {
  const rows = [{ recorded_at: '2026-11-22T12:00:00Z', gas_level: null, gas_alert: false, moisture_level: null, water_detected: false }];
  const groups = groupReadings(rows, 'esp32');
  const flag = (id: string, key: string) => groups.find((g) => g.id === id)?.rows.find((r) => r.key === key);
  assert.equal(flag('gas', 'gas_alert')?.value, null);
  assert.equal(flag('moisture', 'water_detected')?.value, null);
  // beside a level from the same sensor the flag is a reading
  const ok = groupReadings([{ recorded_at: '2026-11-22T12:00:00Z', gas_level: 120, gas_alert: false }], 'esp32');
  assert.equal(ok.find((g) => g.id === 'gas')?.rows.find((r) => r.key === 'gas_alert')?.value, false);
  const raised = groupReadings([{ recorded_at: '2026-11-22T12:00:00Z', gas_level: 900, gas_alert: true }], 'esp32');
  assert.equal(raised.find((g) => g.id === 'gas')?.rows.find((r) => r.key === 'gas_alert')?.value, true);
});

test('a raised alarm is always shown as raised and a clear flag needs its sensor beside it', () => {
  const at = '2026-11-22T12:00:00Z';
  const row = (groups: ReturnType<typeof groupReadings>, id: string, key: string) => groups.find((g) => g.id === id)?.rows.find((x) => x.key === key);
  // gas alarm true with no level: raised
  assert.equal(row(groupReadings([{ recorded_at: at, gas_level: null, gas_alert: true }], 'esp32'), 'gas', 'gas_alert')?.value, true);
  // water true with no moisture level: raised
  assert.equal(row(groupReadings([{ recorded_at: at, moisture_level: null, water_detected: true }], 'esp32'), 'moisture', 'water_detected')?.value, true);
  // Nano water true with no Nano moisture: raised
  assert.equal(row(groupReadings([{ recorded_at: at, nano_moist: null, nano_water: true }], 'esp32'), 'nano_inputs', 'nano_water')?.value, true);
  // clipping true with no strength values: raised
  assert.equal(row(groupReadings([{ recorded_at: at, vib_rms_x: null, vib_clipping: true }], 'esp32'), 'vib_strength', 'vib_clipping')?.value, true);
  // false without its level: no reading. False beside its level: clear.
  assert.equal(row(groupReadings([{ recorded_at: at, gas_level: null, gas_alert: false }], 'esp32'), 'gas', 'gas_alert')?.value, null);
  assert.equal(row(groupReadings([{ recorded_at: at, gas_level: 100, gas_alert: false }], 'esp32'), 'gas', 'gas_alert')?.value, false);
  // an older raised alarm still shows when the newest rows hold a flag the sensor never sent
  const older = groupReadings([{ recorded_at: '2026-11-22T12:00:05Z', gas_level: null, gas_alert: false }, { recorded_at: at, gas_level: null, gas_alert: true }], 'esp32');
  assert.equal(row(older, 'gas', 'gas_alert')?.value, true);
  assert.equal(isRaised(row(older, 'gas', 'gas_alert')!), true);
});
