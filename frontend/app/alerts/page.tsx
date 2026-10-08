'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import api from '@/lib/api';
import type { Alert, Device } from '@/types';
import Card from '@/components/ui/Card';
import PageHeader from '@/components/ui/PageHeader';
import Segmented from '@/components/ui/Segmented';
import EmptyState from '@/components/ui/EmptyState';

// a dot and a word for each severity, so the colour is never the only signal
const SEVERITY: Record<string, { dot: string; text: string; label: string }> = {
  info: { dot: 'bg-primary-500', text: 'text-primary-700 dark:text-primary-300', label: 'Info' },
  warning: { dot: 'bg-warning-500', text: 'text-warning-700 dark:text-warning-400', label: 'Warning' },
  critical: { dot: 'bg-critical-500', text: 'text-critical-700 dark:text-critical-400', label: 'Critical' },
};

const VIEWS = [
  { value: 'active', label: 'Active' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'all', label: 'All' },
] as const;
type View = (typeof VIEWS)[number]['value'];

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [devices, setDevices] = useState<Record<string, string>>({});
  const [view, setView] = useState<View>('active');

  const load = () => api.get<Alert[]>('/alerts').then((r) => setAlerts(r.data));

  useEffect(() => {
    load();
    api.get<Device[]>('/devices').then((r) => setDevices(Object.fromEntries(r.data.map((d) => [d.id, d.name])))).catch(() => {});
  }, []);

  const resolve = async (id: string) => {
    await api.patch(`/alerts/${id}/resolve`);
    load();
  };

  const shown = alerts.filter((a) => view === 'all' || (view === 'active' ? !a.resolved : a.resolved));
  const active = alerts.filter((a) => !a.resolved).length;

  return (
    <main className="mx-auto max-w-6xl space-y-6 p-6">
      <PageHeader
        title="Alerts"
        description={`${active} active. Alerts come from your rules and from the anomaly model.`}
        actions={<Segmented label="Show" options={VIEWS} value={view} onChange={setView} />}
      />
      <Card bodyClassName="divide-y divide-surface-200 dark:divide-surface-800">
        {shown.length === 0 ? (
          <EmptyState heading={view === 'active' ? 'No active alerts' : 'No alerts here'} subMessage="Every machine is inside its normal range." />
        ) : (
          shown.map((a) => {
            const s = SEVERITY[a.severity ?? 'info'] ?? SEVERITY.info;
            return (
              <div key={a.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 text-sm">
                <span className={`inline-flex w-20 shrink-0 items-center gap-1.5 text-xs font-semibold ${s.text}`}>
                  <span className={`h-2 w-2 rounded-full ${s.dot}`} aria-hidden="true" />
                  {s.label}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-surface-800 dark:text-surface-200">{a.message}</p>
                  <p className="mt-0.5 text-xs text-surface-500">
                    {devices[a.device_id] ?? 'Unknown machine'} · {a.rule_id === null ? 'Anomaly model' : 'Alert rule'} ·{' '}
                    {new Date(a.triggered_at).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}
                  </p>
                </div>
                {a.resolved ? (
                  <span className="text-xs text-surface-500">Resolved</span>
                ) : (
                  <div className="flex items-center gap-4">
                    <Link href={`/devices/${a.device_id}`} className="text-xs font-medium text-brand-600 hover:underline dark:text-brand-400">View machine</Link>
                    <button type="button" onClick={() => resolve(a.id)} className="rounded-md border border-surface-200 px-2.5 py-1 text-xs font-medium text-surface-700 hover:bg-surface-50 dark:border-surface-700 dark:text-surface-200 dark:hover:bg-surface-800">
                      Resolve
                    </button>
                  </div>
                )}
              </div>
            );
          })
        )}
      </Card>
    </main>
  );
}
