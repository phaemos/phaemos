// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { monitoringAlertText } from './alertText.ts';

const SENSORS = new Map([['bme280', 'air sensor'], ['stm32_link', 'link to the vibration node']]);
const STATES = new Map([['missing', 'not answering'], ['silent', 'silent'], ['intermittent', 'dropping in and out']]);
const METRICS = new Map([['humidity', 'humidity'], ['vibration_x', 'vibration X']]);
const names = {
  sensor: (k: string) => SENSORS.get(k) ?? `unknown sensor (${k})`,
  state: (s: string) => STATES.get(s) ?? s,
  metric: (f: string) => METRICS.get(f) ?? f,
};

test('a sensor alert names the sensor and the state in words', () => {
  assert.equal(monitoringAlertText('Pump: sensor bme280 is not answering (missing)', 'bme280', names), 'Air sensor not answering');
  assert.equal(monitoringAlertText('Pump: sensor stm32_link is silent (silent)', 'stm32_link', names), 'Link to the vibration node silent');
});

test('a resolved sensor alert keeps its ending in words', () => {
  assert.equal(
    monitoringAlertText('Pump: sensor bme280 is not answering (missing) (resolved: the sensor has reported ok for a minute)', 'bme280', names),
    'Air sensor not answering (resolved: the sensor reported ok for a minute)',
  );
});

test('an intermittent sensor says how often it changed', () => {
  assert.equal(
    monitoringAlertText('Pump: sensor bme280 is intermittent (it changed between working and faulty 7 times in the last hour)', 'bme280', names),
    'Air sensor dropping in and out: it changed between working and faulty 7 times in the last hour',
  );
});

test('a sensor message that does not match keeps its words with the key replaced', () => {
  assert.equal(monitoringAlertText('Pump: bme280 odd', 'bme280', names), 'bme280 odd'.replace('bme280', 'air sensor'));
});

test('a silent node is not given the stale duration from the moment it was raised', () => {
  assert.equal(monitoringAlertText('Pump has not reported for 2 minutes', null, names), 'Stopped reporting');
  assert.equal(monitoringAlertText('Pump has not reported for 2 minutes (back online after 7 min 30 s)', null, names), 'Stopped reporting (back online after 7 min 30 s)');
});

test('a restart loop and a model with no scored reading', () => {
  assert.equal(monitoringAlertText('Pump has restarted 3 times in 10 minutes', null, names), 'Restarted 3 times in 10 minutes');
  assert.equal(
    monitoringAlertText('Pump has had no scored reading for 10 minutes: the model is missing humidity, vibration_x', null, names),
    'No scored reading for 10 minutes. The model is missing humidity and vibration X',
  );
  assert.equal(
    monitoringAlertText('Pump has had no scored reading for 10 minutes: the model is missing humidity', null, names),
    'No scored reading for 10 minutes. The model is missing humidity',
  );
});

test('any other message comes back as it was and an empty one says so', () => {
  assert.equal(monitoringAlertText('Something else', null, names), 'Something else');
  assert.equal(monitoringAlertText(null, null, names), 'No message');
  assert.equal(monitoringAlertText('Pump: sensor constructor is missing (missing)', 'constructor', names), 'Unknown sensor (constructor) not answering');
});

test('the kind the API sends chooses the words', () => {
  assert.equal(monitoringAlertText("Pump: vibration is beyond the sensor's range", null, names, 'clipping'), "Vibration is beyond the sensor's range, so its readings are cut off");
  assert.equal(
    monitoringAlertText("Pump: vibration is beyond the sensor's range (resolved: back inside)", null, names, 'clipping'),
    "Vibration is beyond the sensor's range, so its readings are cut off (resolved: it is back inside the range)",
  );
  assert.equal(monitoringAlertText('Pump has not reported for 2 minutes', null, names, 'offline'), 'Stopped reporting');
  assert.equal(monitoringAlertText('Pump has restarted 3 times in 10 minutes', null, names, 'reset_loop'), 'Restarted 3 times in 10 minutes');
  assert.equal(monitoringAlertText('Pump: sensor bme280 is not answering (missing)', 'bme280', names, 'sensor'), 'Air sensor not answering');
  // no kind (an older API) falls back to the message
  assert.equal(monitoringAlertText('Pump has not reported for 2 minutes', null, names), 'Stopped reporting');
});

test('a board mismatch alert reads in plain words', () => {
  assert.equal(monitoringAlertText('Pump: firmware built for another board', null, names, 'board_mismatch'), 'The firmware image on this node does not match its board');
});
