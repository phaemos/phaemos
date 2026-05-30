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
    bg: 'bg-green-900/50 text-green-400 border border-green-700',
    dot: 'bg-green-400',
    label: 'Online',
  },
  normal: {
    bg: 'bg-green-900/50 text-green-400 border border-green-700',
    dot: 'bg-green-400',
    label: 'Normal',
  },
  offline: {
    bg: 'bg-gray-800 text-gray-400 border border-gray-600',
    dot: 'bg-gray-400',
    label: 'Offline',
  },
  warning: {
    bg: 'bg-amber-900/50 text-amber-400 border border-amber-700',
    dot: 'bg-amber-400',
    label: 'Warning',
  },
  fault: {
    bg: 'bg-red-900/50 text-red-400 border border-red-700',
    dot: 'bg-red-400',
    label: 'Fault',
  },
  anomaly: {
    bg: 'bg-red-900/50 text-red-400 border border-red-700',
    dot: 'bg-red-400',
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
