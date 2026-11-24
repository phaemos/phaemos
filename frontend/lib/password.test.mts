import { test } from 'node:test';
import assert from 'node:assert/strict';
import { passwordRules, passwordProblem } from './password.ts';

const met = (p: string) => Object.fromEntries(passwordRules(p).map((r) => [r.id, r.met]));

test('a short password fails the length rule only when under 8 characters', () => {
  assert.equal(met('Abcdef1').length, false);
  assert.equal(met('Abcdefg1').length, true);
});

test('capital letter and digit rules', () => {
  assert.equal(met('abcdefg1').upper, false);
  assert.equal(met('Abcdefgh').digit, false);
  assert.equal(met('Abcdefg1').upper, true);
  assert.equal(met('Abcdefg1').digit, true);
});

test('the limit is 72 bytes, not 72 characters', () => {
  assert.equal(met('A1' + 'a'.repeat(70)).bytes, true);
  assert.equal(met('A1' + 'a'.repeat(71)).bytes, false);
  // each of these is two bytes in UTF-8
  assert.equal(met('A1' + 'é'.repeat(35)).bytes, true);
  assert.equal(met('A1' + 'é'.repeat(36)).bytes, false);
});

test('passwordProblem names the first rule that fails and is null when all pass', () => {
  assert.equal(passwordProblem('Abcdefg1'), null);
  assert.equal(passwordProblem('Ab1'), 'The password needs at least 8 characters.');
  assert.equal(passwordProblem('abcdefgh1'), 'The password needs a capital letter.');
  assert.equal(passwordProblem('Abcdefghi'), 'The password needs a number.');
});
