'use client';

// I accept both device status strings and alert severity strings so this
// component works in both device cards and alert rows without needing two
// separate badge components.

interface Props {
  status: 'online' | 'offline' | 'warning' | 'fault' | 'normal' | 'anomaly';
}

const statusConfig: Record<
  Props['status'],
  { bg: string; dot: string; label: string }
> = {
  online: {
    bg: 'bg-success-50 dark:bg-success-600/20 text-success-600 dark:text-success-500 border border-success-50 dark:border-success-600/30',
    dot: 'bg-success-500 dark:bg-success-500',
    label: 'Online',
  },
  normal: {
    bg: 'bg-success-50 dark:bg-success-600/20 text-success-600 dark:text-success-500 border border-success-50 dark:border-success-600/30',
    dot: 'bg-success-500 dark:bg-success-500',
    label: 'Normal',
  },
  offline: {
    bg: 'bg-surface-100 dark:bg-surface-800 text-surface-600 dark:text-surface-400 border border-surface-200 dark:border-surface-700',
    dot: 'bg-surface-400',
    label: 'Offline',
  },
  warning: {
    bg: 'bg-amber-100 dark:bg-amber-900/50 text-amber-700 dark:text-amber-400 border border-amber-400 dark:border-amber-700',
    dot: 'bg-amber-500 dark:bg-amber-400',
    label: 'Warning',
  },
  fault: {
    bg: 'bg-critical-50 dark:bg-critical-600/20 text-critical-600 dark:text-critical-400 border border-critical-50 dark:border-critical-600/30',
    dot: 'bg-critical-500 dark:bg-critical-400',
    label: 'Fault',
  },
  anomaly: {
    bg: 'bg-critical-50 dark:bg-critical-600/20 text-critical-600 dark:text-critical-400 border border-critical-50 dark:border-critical-600/30',
    dot: 'bg-critical-500 dark:bg-critical-400',
    label: 'Anomaly',
  },
};

export default function StatusBadge({ status }: Props) {
  const cfg = statusConfig[status] ?? statusConfig.offline;

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium ${cfg.bg}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
      {cfg.label}
    </span>
  );
}
