import { test } from 'node:test';
import assert from 'node:assert/strict';
import { lookup } from './lookup.ts';

test('only the names a table holds are answered', () => {
  const table = { google: 'Google' };
  assert.equal(lookup(table, 'google'), 'Google');
  for (const key of ['constructor', 'toString', 'hasOwnProperty', '__proto__', 'valueOf', 'nope', '']) assert.equal(lookup(table, key), undefined, key);
  assert.equal(lookup(table, null), undefined);
});
