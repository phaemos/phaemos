'use client';

import { Suspense, useCallback, useMemo } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import type { Alert, Device } from '@/types';
import { useApiResource } from '@/hooks/useApiResource';
import TelemetryChart from '@/components/TelemetryChart';
import EmptyState from '@/components/ui/EmptyState';
import ErrorNotice from '@/components/ui/ErrorNotice';
import PageHeader from '@/components/ui/PageHeader';
import { Skeleton, SkeletonGroup } from '@/components/ui/Skeleton';
import { LinkBadge, MachineBadge } from '@/components/machines/MachineStatus';
import { AlertsGapProvider } from '@/components/machines/AlertsGap';
import { alertsGap } from '@/lib/machineState';
import type { Range } from '@/lib/telemetryRange';

const MAX_COMPARE = 3;
// the most machines one request asks for. The API default is 20, which would hide the rest of a larger fleet
const LIMIT = 200;

// one column per picked machine from 1024 px and a single stack below, where three charts side by side are unreadable;
// the classes are written out so Tailwind finds them
const COLUMNS: Record<number, string> = { 1: 'lg:grid-cols-1', 2: 'lg:grid-cols-2', 3: 'lg:grid-cols-3' };

// the machines picked and the time range live in the address, which a page can only read inside a Suspense boundary, so a
// comparison can be linked and survives a reload
export default function ComparePage() {
  return (
    <Suspense fallback={<SkeletonGroup label="Loading the comparison" className="space-y-3"><Skeleton className="h-[72px] rounded-lg" /></SkeletonGroup>}>
      <Compare />
    </Suspense>
  );
}

const ID_PATTERN = /^[0-9a-f-]{8,64}$/i;
const RANGES = ['1h', '6h', '24h', '7d'] as const;

function Compare() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const selected = useMemo(() => (params.get('machines') ?? '').split(',').filter((s) => ID_PATTERN.test(s)).slice(0, MAX_COMPARE), [params]);
  const rangeParam = params.get('range');
  const range: Range = (RANGES as readonly string[]).includes(rangeParam ?? '') ? (rangeParam as Range) : '1h';
  const update = useCallback(
    (patch: { machines?: string[]; range?: Range }) => {
      const q = new URLSearchParams(params.toString());
      const machines = patch.machines ?? selected;
      if (machines.length) q.set('machines', machines.join(','));
      else q.delete('machines');
      const r = patch.range ?? range;
      if (r === '1h') q.delete('range');
      else q.set('range', r);
      const s = q.toString();
      router.replace(s ? `${pathname}?${s}` : pathname, { scroll: false });
    },
    [params, selected, range, pathname, router],
  );

  const { data, error, loading, retry } = useApiResource<Device[]>('/devices', { params: { limit: LIMIT }, what: 'The machines' });
  // the active machine alerts, so each machine's state can say Warning or Fault
  const alertsRes = useApiResource<Alert[]>('/alerts', { params: { resolved: false, category: 'machine', limit: 500 }, what: 'The alerts', intervalMs: 15000 });
  const alerts = alertsRes.data ?? [];
  const gap = alertsGap(alertsRes);

  const toggle = (id: string) => {
    update({ machines: selected.includes(id) ? selected.filter((s) => s !== id) : selected.length < MAX_COMPARE ? [...selected, id] : selected });
  };

  const header = <PageHeader title="Compare" description={`Pick up to ${MAX_COMPARE} machines to see their readings side by side.`} />;

  if (loading) {
    return (
      <div className="space-y-6">
        {header}
        <SkeletonGroup label="Loading machines" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[72px] rounded-lg" />)}
        </SkeletonGroup>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="space-y-6">
        {header}
        <ErrorNotice message={error ?? 'The machines did not load.'} onRetry={retry} />
      </div>
    );
  }

  const devices = data;
  const full = selected.length >= MAX_COMPARE;

  return (
    <AlertsGapProvider gap={gap}>
    <div className="space-y-6">
      {header}

      {gap && (alertsRes.error || alertsRes.data) && <ErrorNotice message="Machines with no active alert show as Unknown." detail={`That is because ${gap}.`} onRetry={alertsRes.retry} />}

      <section aria-labelledby="pick-title" className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4">
          <h2 id="pick-title" className="text-base font-semibold text-surface-900 dark:text-surface-50">Choose machines</h2>
          <p className="text-meta text-surface-600 dark:text-surface-400" aria-live="polite">
            {selected.length} of {MAX_COMPARE} picked{full ? '. Remove one to pick another.' : ''}
          </p>
        </div>

        {error && <ErrorNotice message="The machines could not be refreshed. This list may be out of date." onRetry={retry} />}

        {devices.length === 0 ? (
          <div className="rounded-lg border border-surface-200 dark:border-surface-800">
            <EmptyState heading="No machines yet" subMessage="There is nothing to compare until a machine is registered." action={{ label: 'Open machines', href: '/devices' }} />
          </div>
        ) : (
          <div role="group" aria-labelledby="pick-title" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {devices.map((d) => {
              const active = selected.includes(d.id);
              const disabled = !active && full;
              return (
                <button
                  key={d.id}
                  type="button"
                  aria-pressed={active}
                  onClick={() => toggle(d.id)}
                  disabled={disabled}
                  className={`rounded-lg border bg-surface-0 p-3 text-left transition-colors dark:bg-surface-900 ${
                    active
                      ? 'border-brand-700 ring-1 ring-brand-700 dark:border-brand-400 dark:ring-brand-400'
                      : disabled
                      ? 'cursor-not-allowed border-surface-200 opacity-60 dark:border-surface-800'
                      : 'border-surface-200 hover:border-surface-500 dark:border-surface-800 dark:hover:border-surface-500'
                  }`}
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="truncate text-base font-semibold text-surface-900 dark:text-surface-50">{d.name}</span>
                    <span className={`h-4 w-4 shrink-0 rounded border ${active ? 'border-brand-700 bg-brand-700 dark:border-brand-400 dark:bg-brand-400' : 'border-surface-500'}`} aria-hidden="true">
                      {active && <svg viewBox="0 0 16 16" className="h-4 w-4 text-white dark:text-surface-950" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M4 8.5l2.5 2.5L12 5.5" /></svg>}
                    </span>
                  </span>
                  <span className="mt-1 block truncate text-meta text-surface-600 dark:text-surface-400">{d.location ?? 'No location'}</span>
                  <span className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5"><MachineBadge device={d} alerts={alerts} /><LinkBadge device={d} prefixed /></span>
                </button>
              );
            })}
          </div>
        )}
      </section>

      {selected.length === 0 && devices.length > 0 && (
        <p className="text-base text-surface-600 dark:text-surface-400">No machines picked yet. Choose two or three above to compare them.</p>
      )}

      {selected.length > 0 && (
        <div className={`grid gap-6 ${COLUMNS[selected.length]}`}>
          {selected.map((deviceId) => {
            const device = devices.find((d) => d.id === deviceId);
            return (
              <section key={deviceId} aria-label={device?.name ?? 'Machine'} className="min-w-0 space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="truncate text-base font-semibold text-surface-900 dark:text-surface-50">
                      <Link href={`/devices/${deviceId}`} className="text-brand-800 underline-offset-2 hover:underline dark:text-brand-400">{device?.name ?? 'Machine'}</Link>
                    </h2>
                    <p className="truncate text-meta text-surface-600 dark:text-surface-400">{device?.location ?? 'No location'}</p>
                  </div>
                  {device && (
                    <span className="flex shrink-0 flex-col items-end gap-0.5">
                      <MachineBadge device={device} alerts={alerts} />
                      <LinkBadge device={device} prefixed />
                    </span>
                  )}
                </div>
                <TelemetryChart deviceId={deviceId} device={device ?? null} compact range={range} onRangeChange={(r) => update({ range: r })} />
              </section>
            );
          })}
        </div>
      )}
    </div>
    </AlertsGapProvider>
  );
}
