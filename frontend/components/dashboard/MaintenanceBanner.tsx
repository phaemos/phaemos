'use client';

import { useEffect, useState } from 'react';
import Time from '@/components/ui/Time';
import InlineError from './InlineError';
import StatusBadge from '@/components/ui/StatusBadge';
import { useApiResource } from '@/hooks/useApiResource';
import { serverNow } from '@/lib/serverClock';

interface MaintenanceWindow {
  id: string;
  label: string;
  start_at: string;
  end_at: string;
}

// maintenance windows change rarely, so the read is every 60 seconds
const POLL_MS = 60_000;

export default function MaintenanceBanner() {
  const { data, error, retry } = useApiResource<MaintenanceWindow[]>('/maintenance-windows', { what: 'The maintenance windows', intervalMs: POLL_MS });
  // the clock moves every 30 seconds so a window that ends is dropped without a new read
  const [now, setNow] = useState(() => serverNow());
  useEffect(() => {
    const id = setInterval(() => setNow(serverNow()), 30_000);
    return () => clearInterval(id);
  }, []);

  // a window that has not started yet is not in progress, so both ends are checked
  const active = (data ?? []).find((w) => new Date(w.start_at).getTime() <= now && new Date(w.end_at).getTime() >= now) ?? null;

  // a failed read must not read as "no maintenance": alerts may be silenced by a window this page cannot see
  if (error && !data) return <InlineError message="Planned maintenance could not be checked, so alerts may be switched off for a machine without this page saying so." onRetry={retry} />;
  if (!active) return null;

  return (
    <div role="status" className="flex items-center gap-3 rounded-lg border border-warning-700 bg-warning-50 px-4 py-3 dark:border-warning-400 dark:bg-surface-900">
      <StatusBadge status="warning" label="Maintenance in progress" />
      <p className="text-base text-surface-900 dark:text-surface-50">
        {active.label}. Alerts are suppressed until <Time value={active.end_at} format="datetime" />.
      </p>
    </div>
  );
}
