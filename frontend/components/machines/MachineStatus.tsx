'use client';

import StatusBadge from '@/components/ui/StatusBadge';
import { formatDateTime, formatDateTimeExact } from '@/lib/format';
import { lastPostWords, linkOf, machineStatus, type AlertLike, type DeviceLike } from '@/lib/machineState';
import { useAlertsGap } from './AlertsGap';
import { serverNow } from '@/lib/serverClock';

interface Props {
  device: DeviceLike;
  // the active alerts of the machine, so the machine's state can name a warning or a fault
  alerts?: readonly AlertLike[];
  // a fixed clock for sample data
  now?: number;
}

// what the machine is: Healthy, Warning, Fault or Unknown. Unknown always carries its reason in words. While the alerts
// read is missing or cut off (AlertsGapProvider) a machine with no visible alert reads Unknown and never Healthy.
export function MachineBadge({ device, alerts = [], now }: Props) {
  const gap = useAlertsGap();
  const s = machineStatus(device, alerts, now ?? serverNow(), gap);
  if (s.state === 'unknown') return <StatusBadge status="unknown" label={`Unknown: ${s.reason ?? 'the dashboard cannot tell'}`} />;
  return <StatusBadge status={s.state} />;
}

// how the machine is watched: Online, Late or Offline, from how recently the node posted. With `prefixed` it reads
// "Link online", so beside the machine's own state it is clear which is which.
export function LinkBadge({ device, now, prefixed = false }: Omit<Props, 'alerts'> & { prefixed?: boolean }) {
  const link = linkOf(device, now ?? serverNow());
  const word = link === 'online' ? 'Online' : link === 'late' ? 'Late' : 'Offline';
  return <StatusBadge status={link} label={prefixed ? `Link ${word.toLowerCase()}` : word} />;
}

// both facts together, one under the other, for a panel
export default function MachineStatus({ device, alerts, now }: Props) {
  return (
    <span className="flex flex-col items-start gap-0.5">
      <MachineBadge device={device} alerts={alerts} now={now} />
      <LinkBadge device={device} now={now} prefixed />
    </span>
  );
}

// the time since the last post. It comes from the API's own figure when there is one, so a browser clock that is wrong
// cannot change it and it is the same figure the state's reason uses. The exact time is in a title.
export function LastPost({ device, now, showExact = false }: Omit<Props, 'alerts'> & { showExact?: boolean }) {
  const words = lastPostWords(device, now ?? serverNow());
  if (!device.last_seen) return <>{words}</>;
  return (
    <time dateTime={new Date(device.last_seen).toISOString()} title={formatDateTimeExact(device.last_seen)} className="tnum">
      {words}
      {showExact ? <span className="ml-1.5 text-meta">({formatDateTime(device.last_seen)})</span> : <span className="sr-only">, {formatDateTime(device.last_seen)}</span>}
    </time>
  );
}
