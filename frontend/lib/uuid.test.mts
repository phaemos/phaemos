import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isUuid } from './uuid.ts';

test('only a UUID is a machine id', () => {
  assert.equal(isUuid('7e7ee2b7-fba7-4918-9f5a-846f9f89b78b'), true);
  assert.equal(isUuid('7E7EE2B7-FBA7-4918-9F5A-846F9F89B78B'), true);
  for (const bad of ['', 'not-a-machine', '7e7ee2b7fba749189f5a846f9f89b78b', '7e7ee2b7-fba7-4918-9f5a-846f9f89b78', '../admin', '7e7ee2b7-fba7-4918-9f5a-846f9f89b78b/x', '7e7ee2b7-fba7-4918-9f5a-846f9f89b78bz', '%00']) assert.equal(isUuid(bad), false, bad);
});
