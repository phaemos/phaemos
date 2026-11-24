import DeviceCard from '@/components/DeviceCard';
import EmptyState from '@/components/ui/EmptyState';
import type { Device } from '@/types';
import Link from 'next/link';
import InlineError from './InlineError';
import type { KeyReading } from './keyReadings';
import type { AlertLike } from '@/lib/machineState';

interface Props {
  devices: Device[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  // headline readings by device id, for the machines the page holds readings for
  readings?: Record<string, KeyReading[]>;
  now?: number;
  // the active alerts, so each panel's machine state can say Warning or Fault
  alerts?: readonly AlertLike[];
  // true until the first answer arrives, so an unanswered request is not shown as "no machines"
  loading?: boolean;
  // the request failed: shown with a retry instead of an empty list
  failed?: boolean;
  onRetry?: () => void;
  // set when the list was cut at the request limit, so the grid says so and links to the full list
  truncatedAt?: number;
  // the API's own count of machines, when it sent one
  total?: number | null;
}

// the machines as a grid of panels. Presentational: the page owns the device list and the selection.
export default function MachineGrid({ devices, selectedId, onSelect, readings, now, alerts, loading, failed, onRetry, truncatedAt, total }: Props) {
  return (
    <section aria-labelledby="machines-title" className="space-y-3">
      <h2 id="machines-title" className="text-sm font-semibold text-surface-900 dark:text-surface-50">Machines</h2>
      {failed && onRetry && <InlineError message={devices.length > 0 ? 'Machines could not be refreshed. This list may be out of date.' : 'Machines could not be loaded.'} onRetry={onRetry} />}
      {devices.length === 0 && (loading || failed) ? (
        failed ? null : <p className="text-sm text-surface-600 dark:text-surface-400">Loading machines</p>
      ) : devices.length === 0 ? (
        <div className="rounded-lg border border-surface-200 dark:border-surface-800">
          <EmptyState
            heading="No machines registered"
            subMessage="A machine appears here once it is registered and its node starts posting readings."
            action={{ label: 'Open machines', href: '/devices' }}
          />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {devices.map((d) => (
            <DeviceCard
              key={d.id}
              device={d}
              active={selectedId === d.id}
              onClick={onSelect ? () => onSelect(d.id) : undefined}
              readings={readings?.[d.id]}
              alerts={alerts}
              now={now}
            />
          ))}
        </div>
      )}
      {truncatedAt !== undefined && devices.length >= truncatedAt && (
        <p className="text-sm text-surface-700 dark:text-surface-300">
          {total && total > devices.length ? `Showing ${devices.length} of ${total} machines.` : `Showing the first ${truncatedAt} machines.`}{' '}
          <Link href="/devices" className="inline-flex min-h-[44px] items-center font-medium text-brand-800 underline dark:text-brand-400">See all machines</Link>
        </p>
      )}
    </section>
  );
}
