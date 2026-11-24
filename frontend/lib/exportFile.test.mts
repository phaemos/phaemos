// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { exportFileName, exportFromTs } from './exportFile.ts';

const NOW = new Date('2026-11-22T12:30:00Z');

test('the window starts 24 hours before now', () => {
  assert.equal(exportFromTs(NOW), '2026-11-21T12:30:00.000Z');
  assert.equal(exportFromTs(NOW, 1), '2026-11-22T11:30:00.000Z');
});

test('the file is named from the machine and the day', () => {
  assert.equal(exportFileName('Boiler room pump', NOW), 'boiler-room-pump-readings-last-24-hours-2026-11-22.csv');
});

test('accents fold and punctuation becomes one hyphen', () => {
  assert.equal(exportFileName('  Café / Pump #3!! ', NOW), 'cafe-pump-3-readings-last-24-hours-2026-11-22.csv');
});

test('a name with nothing usable falls back to machine and a long one is cut', () => {
  assert.equal(exportFileName('???', NOW), 'machine-readings-last-24-hours-2026-11-22.csv');
  assert.ok(exportFileName('a'.repeat(200), NOW).startsWith('a'.repeat(60) + '-readings'));
});
