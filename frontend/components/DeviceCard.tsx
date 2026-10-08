import type { Device } from '@/types';

interface Props {
  device: Device;
  active: boolean;
  onClick: () => void;
}

// a dot and a word for each state, so the colour is never the only signal
const statusConfig: Record<string, { dot: string; label: string }> = {
  online: { dot: 'bg-success-500', label: 'Online' },
  offline: { dot: 'bg-surface-400', label: 'Offline' },
  warning: { dot: 'bg-warning-500', label: 'Warning' },
  fault: { dot: 'bg-critical-500', label: 'Fault' },
};

const NODE_LABELS: Record<string, string> = {
  esp32: 'ESP32 hub',
  stm32: 'STM32 vibration node',
  nano: 'Arduino Nano node',
  pico_w: 'Pico 2 W ambient node',
};

function lastSeen(iso: string | null): string {
  if (!iso) return 'Never seen';
  const secs = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (secs < 60) return 'Seen just now';
  if (secs < 3600) return `Seen ${Math.round(secs / 60)} min ago`;
  return `Seen ${new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}`;
}

export default function DeviceCard({ device, active, onClick }: Props) {
  const cfg = statusConfig[device.status] ?? statusConfig.offline;

  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`w-full rounded-lg border bg-white p-4 text-left transition-colors dark:bg-surface-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500 ${
        active
          ? 'border-brand-500 ring-1 ring-brand-500'
          : 'border-surface-200 hover:border-surface-300 dark:border-surface-800 dark:hover:border-surface-700'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-surface-900 dark:text-surface-50">{device.name}</p>
          <p className="mt-0.5 truncate text-xs text-surface-500 dark:text-surface-400">{device.location ?? 'No location'}</p>
        </div>
        <span className="inline-flex shrink-0 items-center gap-1.5 text-xs font-medium text-surface-700 dark:text-surface-300">
          <span className={`h-2 w-2 rounded-full ${cfg.dot}`} aria-hidden="true" />
          {cfg.label}
        </span>
      </div>
      <div className="mt-3 flex items-center justify-between gap-3 border-t border-surface-100 pt-3 text-xs text-surface-500 dark:border-surface-800 dark:text-surface-400">
        <span>{NODE_LABELS[device.type ?? ''] ?? device.type ?? 'Unknown node'}</span>
        <span>{lastSeen(device.last_seen)}</span>
      </div>
      {device.tags && device.tags.length > 0 && (
        <p className="mt-2 text-xs text-surface-500 dark:text-surface-400">{device.tags.join(' · ')}</p>
      )}
    </button>
  );
}
