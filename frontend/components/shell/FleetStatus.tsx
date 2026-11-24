import { StatusShape } from '@/components/ui/StatusBadge';
import type { ShellStale, ShellStatus } from '@/hooks/useShellStatus';

// the clock time of the last good answer, for "no answer since 14:02"
function formatTime(ms: number): string {
  return new Date(ms).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
}

// the fleet by link state: "9 online, 1 late, 2 offline", with a shape and words, never colour alone. A late or offline
// node is a warning, because a machine whose node is silent is not being watched. Late is left out when it is zero;
// it sits under the emblem in the sidebar from 1024 px and in the bar below that.
export default function FleetStatus({ status, stale }: { status: ShellStatus | null; stale?: ShellStale | null }) {
  // when the reads have stopped answering the old figures are not shown as if they were current
  if (stale) {
    return (
      <p role="status" className="inline-flex items-center gap-2 text-meta font-medium text-surface-800 dark:text-surface-200">
        <span className="text-warning-800 dark:text-warning-400"><StatusShape shape="ring" /></span>
        <span>{stale.since ? `Status unknown: no answer since ${formatTime(stale.since)}` : 'Status unknown: no answer yet'}</span>
      </p>
    );
  }
  if (!status) {
    return (
      <p className="inline-flex items-center gap-2 text-meta text-surface-600 dark:text-surface-400">
        <StatusShape shape="ring" />
        <span>Fleet status loading</span>
      </p>
    );
  }
  const attention = status.late > 0 || status.offline > 0;
  return (
    <p className="inline-flex items-center gap-2 text-meta font-medium text-surface-800 dark:text-surface-200">
      <span className={attention ? 'text-warning-800 dark:text-warning-400' : 'text-success-800 dark:text-success-400'}>
        <StatusShape shape={attention ? 'triangle' : 'circle'} />
      </span>
      <span className="tnum">
        {status.online} online{status.late > 0 ? `, ${status.late} late` : ''}, {status.offline} offline
      </span>
    </p>
  );
}
