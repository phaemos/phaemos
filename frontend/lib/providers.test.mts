// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseProviders } from './providers.ts';

test('only the configured providers are listed, in a fixed order', () => {
  assert.deepEqual(parseProviders({ providers: ['microsoft', 'google'] }), ['google', 'microsoft']);
  assert.deepEqual(parseProviders({ providers: ['github'] }), ['github']);
});

test('an unknown provider is ignored', () => {
  assert.deepEqual(parseProviders({ providers: ['google', 'okta'] }), ['google']);
});

test('anything else gives none, so no button is shown', () => {
  assert.deepEqual(parseProviders(null), []);
  assert.deepEqual(parseProviders({}), []);
  assert.deepEqual(parseProviders({ providers: 'google' }), []);
  assert.deepEqual(parseProviders({ providers: [] }), []);
});
