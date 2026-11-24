'use client';

import { countBySeverity } from '../../lib/alertGroups';
import { useApiResource } from '@/hooks/useApiResource';
import type { Alert, Device } from '../../types/index';
import InlineError from './InlineError';
import { Skeleton, SkeletonGroup } from '@/components/ui/Skeleton';
import { countFleet, linkOf } from '@/lib/machineState';
import { serverNow } from '@/lib/serverClock';
import StatStrip, { type HealthData } from './StatStrip';

interface Props {
  // the page already polls the active alerts, so the severity split reuses that list
  alerts: Alert[];
  // the machines the page holds once they have loaded, so the bar can count each once by its state. Left out while loading.
  devices?: Device[];
  // why the alerts read cannot be trusted, in words or null. While it is set no machine counts as healthy.
  alertsGap?: string | null;
}

// the machines on the page are the source for how many are online, late and offline when the page holds the whole fleet, because
// they are judged by one rule (lib/machineState.ts) that also decides every badge. The summary's own counts are used only when the
// list is cut short. The page's own count of machines then also agrees with the cards.
function withLinks(data: HealthData, devices?: Device[]): HealthData {
  if (!devices || devices.length === 0 || devices.length < data.total_devices) return data;
  const links = { online: 0, late: 0, offline: 0 };
  const now = serverNow();
  for (const d of devices) links[linkOf(d, now)] += 1;
  return { ...data, total_devices: devices.length, online: links.online, offline: links.offline, link_states: links };
}

// fetches the fleet summary and hands it to the presentational strip
export default function HealthSummary({ alerts, devices, alertsGap = null }: Props) {
  const { data, error, retry } = useApiResource<HealthData>('/fleet/summary', { what: 'The fleet summary', intervalMs: 30_000 });

  if (error && !data) return <InlineError message="The fleet summary could not be loaded." onRetry={retry} />;

  if (!data) {
    // the same height as the loaded strip so the page does not jump
    return (
      <SkeletonGroup label="Loading the fleet summary" className="min-h-[188px] rounded-lg border border-surface-200 bg-surface-0 p-4 dark:border-surface-800 dark:bg-surface-900">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="mt-3 h-7 w-56" />
        <Skeleton className="mt-3 h-2.5 w-full max-w-sm" />
      </SkeletonGroup>
    );
  }

  return (
    <div className="space-y-3">
      {error && <InlineError message="The fleet summary could not be refreshed. These numbers may be out of date." onRetry={retry} />}
      <StatStrip
        data={withLinks(data, devices)}
        severity={countBySeverity(alerts)}
        alertsGap={alertsGap}
        split={devices ? countFleet(devices, alerts, serverNow(), alertsGap) : undefined}
      />
    </div>
  );
}
