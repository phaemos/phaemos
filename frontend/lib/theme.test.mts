import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { THEME_COLOR } from './theme.ts';

test('the theme file holds the same two colours as lib/theme.ts', () => {
  const file = readFileSync(new URL('../public/theme.js', import.meta.url), 'utf8');
  assert.ok(file.includes(`'${THEME_COLOR.light}'`) && file.includes(`'${THEME_COLOR.dark}'`));
});
