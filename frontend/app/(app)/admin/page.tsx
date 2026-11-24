'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { ADMIN_TABS, adminTabHref, parseAdminTab } from '@/lib/adminTabs';
import { useRole } from '@/hooks/useRole';
import { roleWord } from '@/lib/format';
import { appPath } from '@/lib/links';
import { LinkButton } from '@/components/ui/Button';
import PageHeader from '@/components/ui/PageHeader';
import Tabs from '@/components/ui/Tabs';
import { SkeletonRows } from '@/components/ui/Skeleton';
import PeoplePanel from '@/components/admin/PeoplePanel';
import AlertRulesPanel from '@/components/admin/AlertRulesPanel';
import WebhooksPanel from '@/components/admin/WebhooksPanel';
import MaintenanceWindowsPanel from '@/components/admin/MaintenanceWindowsPanel';
import AuditLog from '@/components/admin/AuditLog';
import FirmwarePanel from '@/components/admin/FirmwarePanel';

const DESCRIPTIONS = {
  users: 'Who can sign in and what each person may do. Invite someone new and manage the people you have.',
  'alert-rules': 'Limits that raise an alert when a reading crosses them.',
  webhooks: 'Where we send alerts besides the dashboard.',
  maintenance: 'Planned work, when alerts for a machine should stay quiet.',
  'audit-log': 'What admins and the system changed, newest first.',
  firmware: 'The build our ESP32 nodes install on their next start.',
} as const;

// useSearchParams needs a Suspense boundary so the page can still be prerendered.
export default function AdminPage() {
  return (
    <Suspense fallback={<div className="p-0"><SkeletonRows rows={4} label="Loading admin" /></div>}>
      <Admin />
    </Suspense>
  );
}

function Admin() {
  const role = useRole();
  const tab = parseAdminTab(useSearchParams().get('tab'));
  const current = ADMIN_TABS.find((t) => t.value === tab) ?? ADMIN_TABS[0];

  // the role is not known on the first render. The API refuses every admin read and write to anyone else, so the page does
  // not offer the tools to a technician or a viewer and says why.
  if (role === null) return <SkeletonRows rows={4} label="Loading admin" />;
  if (role !== 'admin') {
    return (
      <div className="space-y-4">
        <PageHeader title="Admin" />
        <p role="note" className="max-w-[72ch] text-base text-surface-800 dark:text-surface-200">
          <span className="font-medium">Admins only.</span> Your account is a {roleWord(role)} account, so it cannot use the admin tools. Ask an admin if something needs changing.
        </p>
        <LinkButton href={appPath('/dashboard')} variant="secondary">Back to the overview</LinkButton>
      </div>
    );
  }

  // the tabs are links, so each tool has its own address that can be shared and survives a reload.
  // only the current panel mounts, so a tab does not fetch until it is opened.
  return (
    <div className="space-y-6">
      <PageHeader title="Admin" description={DESCRIPTIONS[tab]} />
      <Tabs label="Admin tools" value={tab} items={ADMIN_TABS.map((t) => ({ value: t.value, label: t.label, href: adminTabHref(t.value) }))} />
      <section aria-label={current.label}>
        {tab === 'users' && <PeoplePanel />}
        {tab === 'alert-rules' && <AlertRulesPanel />}
        {tab === 'webhooks' && <WebhooksPanel />}
        {tab === 'maintenance' && <MaintenanceWindowsPanel />}
        {tab === 'audit-log' && <AuditLog />}
        {tab === 'firmware' && <FirmwarePanel />}
      </section>
    </div>
  );
}
