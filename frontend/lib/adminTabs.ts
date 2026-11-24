// the admin tools, one per tab. The current tab lives in the address (?tab=) so a tab can be linked and a
// reload keeps its place.

export const ADMIN_TABS = [
  { value: 'users', label: 'People' },
  { value: 'alert-rules', label: 'Alert rules' },
  { value: 'webhooks', label: 'Webhooks' },
  { value: 'maintenance', label: 'Maintenance windows' },
  { value: 'audit-log', label: 'Audit log' },
  { value: 'firmware', label: 'Firmware' },
] as const;

export type AdminTab = (typeof ADMIN_TABS)[number]['value'];

export const DEFAULT_ADMIN_TAB: AdminTab = 'users';

// an unknown, repeated or missing value falls back to the first tab instead of showing a blank page
export function parseAdminTab(value: string | string[] | null | undefined): AdminTab {
  const first = Array.isArray(value) ? value[0] : value;
  const found = ADMIN_TABS.find((t) => t.value === first);
  return found ? found.value : DEFAULT_ADMIN_TAB;
}

export function adminTabHref(tab: AdminTab): string {
  return tab === DEFAULT_ADMIN_TAB ? '/admin' : `/admin?tab=${tab}`;
}
