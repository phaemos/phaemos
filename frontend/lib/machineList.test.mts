// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DEFAULT_MACHINE_VIEW, countLine, filterMachines, machineViewToQuery, ownerLabel, parseMachineView, sortMachines, tagCounts, type MachineLike } from './machineList.ts';

const m = (over: Partial<MachineLike> & { name: string }): MachineLike => ({
  id: over.name, location: null, type: null, status: 'online', last_seen: null, tags: [], ...over,
});

const fleet = [
  m({ name: 'Pump 10', status: 'online', last_seen: '2026-11-22T10:00:00Z', location: 'Yard', tags: ['pumps', 'north'] }),
  m({ name: 'Pump 2', status: 'fault', last_seen: '2026-11-22T09:00:00Z', location: 'Boiler room', tags: ['pumps'] }),
  m({ name: 'Fan', status: 'offline', last_seen: null, tags: null }),
  m({ name: 'Chiller', status: 'warning', last_seen: '2026-11-22T11:00:00Z', location: 'Annex' }),
];

test('attention order puts fault, warning, offline then online and breaks ties by name', () => {
  assert.deepEqual(sortMachines(fleet, 'attention').map((x) => x.name), ['Pump 2', 'Chiller', 'Fan', 'Pump 10']);
});

test('name order is natural so Pump 2 comes before Pump 10', () => {
  assert.deepEqual(sortMachines(fleet, 'name').map((x) => x.name), ['Chiller', 'Fan', 'Pump 2', 'Pump 10']);
});

test('last seen puts the newest first and a machine that never reported last', () => {
  assert.deepEqual(sortMachines(fleet, 'recent').map((x) => x.name), ['Chiller', 'Pump 10', 'Pump 2', 'Fan']);
});

test('location order puts a missing location last', () => {
  assert.deepEqual(sortMachines(fleet, 'location').map((x) => x.name), ['Chiller', 'Pump 2', 'Pump 10', 'Fan']);
});

test('sorting does not change the input', () => {
  const before = fleet.map((x) => x.name);
  sortMachines(fleet, 'name');
  assert.deepEqual(fleet.map((x) => x.name), before);
});

test('filters combine and a search ignores case', () => {
  assert.deepEqual(filterMachines(fleet, { status: '', tag: 'pumps', search: '' }).map((x) => x.name), ['Pump 10', 'Pump 2']);
  assert.deepEqual(filterMachines(fleet, { status: 'fault', tag: 'pumps', search: '' }).map((x) => x.name), ['Pump 2']);
  assert.deepEqual(filterMachines(fleet, { status: '', tag: '', search: ' CHILL ' }).map((x) => x.name), ['Chiller']);
  assert.equal(filterMachines(fleet, { status: 'online', tag: 'north', search: 'fan' }).length, 0);
});

test('tag counts are sorted and tolerate a null tag list', () => {
  assert.deepEqual(tagCounts(fleet), [{ tag: 'north', count: 1 }, { tag: 'pumps', count: 2 }]);
});

test('the count line is truthful about what a filter hides', () => {
  assert.equal(countLine(4, 4), '4 machines');
  assert.equal(countLine(1, 1), '1 machine');
  assert.equal(countLine(2, 4), 'Showing 2 of 4 machines');
});

test('an owner is never reported unassigned when the API says there is one', () => {
  assert.equal(ownerLabel(null, { names: {} }), 'Unassigned');
  assert.equal(ownerLabel('u1', { names: { u1: 'Sam Hill' } }), 'Sam Hill');
  assert.equal(ownerLabel('u1', { names: {}, me: { id: 'u1', name: null, email: 'sam@example.com' } }), 'sam@example.com (you)');
  assert.equal(ownerLabel('u2', { names: {}, me: { id: 'u1', name: 'Sam', email: 'sam@example.com' } }), 'Another technician');
});

test('the machines view round-trips through the address', () => {
  const view = { search: 'pump', state: 'warning', link: 'late', tag: 'lab', sort: 'name' as const };
  const query = machineViewToQuery(view);
  assert.equal(query, 'q=pump&state=warning&link=late&tag=lab&sort=name');
  assert.deepEqual(parseMachineView(new URLSearchParams(query)), view);
});

test('the plain machines view has a plain address', () => {
  assert.equal(machineViewToQuery(DEFAULT_MACHINE_VIEW), '');
  assert.deepEqual(parseMachineView(new URLSearchParams('')), DEFAULT_MACHINE_VIEW);
});

test('an unknown status or sort falls back to the default', () => {
  const view = parseMachineView(new URLSearchParams('state=melting&link=sideways&sort=sideways'));
  assert.equal(view.state, '');
  assert.equal(view.link, '');
  assert.equal(view.sort, 'attention');
});

test('an attention sort can use a rank the page supplies', () => {
  const list = [m({ name: 'A' }), m({ name: 'B' }), m({ name: 'C' })];
  const rank = (x: MachineLike) => (x.name === 'C' ? 0 : x.name === 'A' ? 1 : 2);
  assert.deepEqual(sortMachines(list, 'attention', rank).map((x) => x.name), ['C', 'A', 'B']);
});
