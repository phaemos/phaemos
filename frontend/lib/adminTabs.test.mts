import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseAdminTab, adminTabHref, ADMIN_TABS } from './adminTabs.ts';

test('a known tab is returned as it is', () => {
  for (const t of ADMIN_TABS) assert.equal(parseAdminTab(t.value), t.value);
});

test('a missing or unknown tab falls back to users', () => {
  assert.equal(parseAdminTab(null), 'users');
  assert.equal(parseAdminTab(undefined), 'users');
  assert.equal(parseAdminTab(''), 'users');
  assert.equal(parseAdminTab('billing'), 'users');
});

test('a repeated parameter uses the first value', () => {
  assert.equal(parseAdminTab(['webhooks', 'users']), 'webhooks');
});

test('the default tab links to the bare path and the others carry the parameter', () => {
  assert.equal(adminTabHref('users'), '/admin');
  assert.equal(adminTabHref('audit-log'), '/admin?tab=audit-log');
});
