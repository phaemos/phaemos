import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cleanPhone, phoneProblem } from './phone.ts';

test('spaces and hyphens are dropped', () => {
  assert.equal(cleanPhone('+44 7700-900 000'), '+447700900000');
});

test('empty and international numbers are accepted', () => {
  assert.equal(phoneProblem(''), null);
  assert.equal(phoneProblem('   '), null);
  assert.equal(phoneProblem('+447700900000'), null);
  assert.equal(phoneProblem('+44 7700 900-000'), null);
});

test('numbers without a plus sign or with a wrong length are refused', () => {
  assert.ok(phoneProblem('07700900000'));
  assert.ok(phoneProblem('447700900000'));
  assert.ok(phoneProblem('+1234567'));
  assert.ok(phoneProblem('+1234567890123456'));
  assert.ok(phoneProblem('+44abc0900000'));
});
