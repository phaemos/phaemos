import type { ReactNode } from 'react';
import { StatusShape, statusShape, type Status } from '@/components/ui/StatusBadge';
import { cn } from '@/lib/cn';
import { plural } from '@/lib/format';
import { fleetSentence, fleetWord, type FleetSplit } from '@/lib/machineState';
import type { Severity } from '@/lib/alertGroups';

export interface HealthData {
  total_devices: number;
  online: number;
  offline: number;
  active_alerts: number;
  open_tickets: number;
  health_score: number;
  // machines by how recently their node posted. Absent from an older API.
  link_states?: { online?: number; late?: number; offline?: number };
}

// the word for the fleet comes from the same split the bar draws, so the word and the bar cannot disagree
const WORD_STATUS = { success: 'healthy', warning: 'warning', critical: 'fault', neutral: 'unknown' } as const;

function Shaped({ status, children }: { status: Status; children: ReactNode }) {
  const s = statusShape(status);
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={s.tone}><StatusShape shape={s.shape} /></span>
      <span>{children}</span>
    </span>
  );
}

function Item({ label, children, note, extra, className }: { label: string; children: ReactNode; note?: ReactNode; extra?: ReactNode; className?: string }) {
  return (
    <div className={cn('min-w-0 bg-surface-0 p-4 dark:bg-surface-900', className)}>
      <dt className="label text-surface-700 dark:text-surface-300">{label}</dt>
      <dd className="tnum mt-1 text-lg font-semibold text-surface-900 dark:text-surface-50">{children}</dd>
      {note && <dd className="mt-0.5 text-sm text-surface-700 dark:text-surface-300">{note}</dd>}
      {extra}
    </div>
  );
}

// the segments of the bar, in a fixed order, with the words the machine badge uses. Each is told apart by its place, its
// legend entry with a shape and a word and, for unknown, an outline instead of a fill. The fills are 3:1 or better against
// the track. A machine counts in the same part as its own badge says.
const SEGMENTS = [
  { key: 'healthy', word: 'healthy', status: 'healthy', fill: 'bg-success-700 dark:bg-success-500' },
  { key: 'warning', word: 'warning', status: 'warning', fill: 'bg-warning-700 dark:bg-warning-500' },
  { key: 'fault', word: 'fault', status: 'fault', fill: 'bg-critical-700 dark:bg-critical-500' },
  { key: 'unknown', word: 'unknown', status: 'unknown', fill: 'border-2 border-surface-600 dark:border-surface-400' },
] as const;

// parts of a whole are what a stacked bar is for: the machines split by state, with the counts as words beside it
function MachineBar({ split }: { split: FleetSplit }) {
  const total = split.healthy + split.warning + split.fault + split.unknown;
  if (total === 0) return null;
  const summary = `${plural(total, 'machine')}: ${SEGMENTS.map((s) => `${split[s.key]} ${s.word}`).join(', ')}`;
  return (
    <div className="mt-3">
      <p className="mb-1.5 text-meta text-surface-700 dark:text-surface-300">Machines by state</p>
      <div role="img" aria-label={summary} className="flex h-2.5 w-full max-w-sm gap-0.5 overflow-hidden rounded-sm bg-surface-100 dark:bg-surface-800">
        {SEGMENTS.filter((s) => split[s.key] > 0).map((s) => (
          <span key={s.key} className={cn('block h-full rounded-sm', s.fill)} style={{ flexGrow: split[s.key], flexBasis: 0 }} />
        ))}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-surface-800 dark:text-surface-200">
        {SEGMENTS.map((s) => (
          <li key={s.key}>
            <Shaped status={s.status}><span className="tnum">{split[s.key]}</span> {s.word}</Shaped>
          </li>
        ))}
      </ul>
    </div>
  );
}

interface Props {
  data: HealthData;
  // the machines counted once each by their worst state (lib/machineState.ts). Without it there is no bar and the word
  // falls back to the health score.
  split?: FleetSplit;
  // active alerts split by severity, counted from the alert list
  severity: Record<Severity, number>;
  // why the alert list cannot be trusted to be whole, in words or null
  alertsGap?: string | null;
}

// the fleet in four lines, each one a figure with the words that say what it means. Presentational: the container
// fetches the summary.
export default function StatStrip({ data, severity, split, alertsGap = null }: Props) {
  const total = severity.critical + severity.warning + severity.info;
  const word = split ? fleetWord(split) : null;
  const links = { online: data.link_states?.online ?? data.online, late: data.link_states?.late ?? 0, offline: data.link_states?.offline ?? data.offline };

  return (
    <section aria-labelledby="fleet-summary" className="overflow-hidden rounded-lg border border-surface-200 dark:border-surface-800">
      <h2 id="fleet-summary" className="sr-only">Fleet summary</h2>
      <dl className="grid grid-cols-1 gap-px bg-surface-200 dark:bg-surface-800 sm:grid-cols-2 lg:grid-cols-5">
        <Item
          className="sm:col-span-2"
          label="Fleet health"
          note={split ? fleetSentence(split) : undefined}
          extra={split ? <MachineBar split={split} /> : undefined}
        >
          {word ? <Shaped status={WORD_STATUS[word.tone]}>{word.word}</Shaped> : <span className="text-surface-700 dark:text-surface-300">Counting machines</span>}
        </Item>
        <Item
          label="Machines"
          note={
            data.total_devices === 0 ? undefined : links.late + links.offline === 0 ? (
              'All reporting'
            ) : (
              <span className="flex flex-wrap gap-x-3 gap-y-1">
                {links.late > 0 && <Shaped status="late">{links.late} late</Shaped>}
                {links.offline > 0 && <Shaped status="offline">{links.offline} offline</Shaped>}
              </span>
            )
          }
        >
          {data.total_devices === 0 ? 'No machines' : `${links.online} of ${data.total_devices} online`}
        </Item>
        <Item
          label="Active alerts"
          note={
            total === 0 ? undefined : (
              <span className="flex flex-wrap gap-x-3 gap-y-1">
                {data.active_alerts > total && <span className="basis-full text-meta">Split of the newest {total}</span>}
                {severity.critical > 0 && <Shaped status="critical">{severity.critical} critical</Shaped>}
                {severity.warning > 0 && <Shaped status="warning">{severity.warning} warning</Shaped>}
                {severity.info > 0 && <Shaped status="info">{severity.info} info</Shaped>}
              </span>
            )
          }
        >
          {data.active_alerts === 0 ? 'None active' : `${data.active_alerts} active`}
          {alertsGap && <span className="sr-only">. The list of alerts is incomplete: {alertsGap}</span>}
        </Item>
        <Item label="Tickets">{data.open_tickets === 0 ? 'None open' : `${data.open_tickets} open`}</Item>
      </dl>
    </section>
  );
}
