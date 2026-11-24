import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mergeFirstPage, nextCursor } from './keyset.ts';

const row = (id: string, at: string) => ({ id, at });
const cur = (r: { id: string; at: string }) => `${r.at},${r.id}`;

test('the next cursor is the header of a full page and nothing for a short one', () => {
  assert.equal(nextCursor('2026-11-22T10:00:00Z,abc', 50, 50), '2026-11-22T10:00:00Z,abc');
  assert.equal(nextCursor('2026-11-22T10:00:00Z,abc', 20, 50), null);
  assert.equal(nextCursor(undefined, 50, 50), null);
  assert.equal(nextCursor('', 50, 50), null);
});

test('a short first page is the whole list and drops everything read before', () => {
  const m = mergeFirstPage([row('a', '2026-11-22T10:05:00Z')], [row('a', '2026-11-22T10:05:00Z'), row('z', '2026-11-22T09:00:00Z')], cur, 50);
  assert.deepEqual(m.items.map((r) => r.id), ['a']);
  assert.equal(m.done, true);
});

test('a full first page keeps the older pages already read and drops rows that left the list', () => {
  const page = [row('n', '2026-11-22T10:10:00Z'), row('b', '2026-11-22T10:05:00Z')];
  const existing = [row('gone', '2026-11-22T10:07:00Z'), row('b', '2026-11-22T10:05:00Z'), row('c', '2026-11-22T10:01:00Z'), row('d', '2026-11-22T10:00:00Z')];
  const m = mergeFirstPage(page, existing, cur, 2);
  assert.deepEqual(m.items.map((r) => r.id), ['n', 'b', 'c', 'd']);
  assert.equal(m.keptOlder, true);
});

test('a row never appears twice and a row arriving live goes to the front', () => {
  const page = [row('live', '2026-11-22T10:20:00Z'), row('a', '2026-11-22T10:10:00Z')];
  const m = mergeFirstPage(page, [row('a', '2026-11-22T10:10:00Z'), row('b', '2026-11-22T10:05:00Z')], cur, 2);
  assert.deepEqual(m.items.map((r) => r.id), ['live', 'a', 'b']);
});

test('with nothing read before, a full page is returned as it is and the caller takes the header', () => {
  const m = mergeFirstPage([row('a', '2026-11-22T10:10:00Z'), row('b', '2026-11-22T10:05:00Z')], [], cur, 2);
  assert.equal(m.items.length, 2);
  assert.equal(m.keptOlder, false);
  assert.equal(m.done, false);
});
