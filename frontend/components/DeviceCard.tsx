import type { Device } from '@/types';

interface Props {
  device: Device;
  active: boolean;
  onClick: () => void;
}

const statusConfig: Record<string, { dot: string; label: string; pulse: boolean }> = {
  online: { dot: 'bg-success-500', label: 'Online', pulse: true },
  offline: { dot: 'bg-surface-600', label: 'Offline', pulse: false },
  warning: { dot: 'bg-warning-500', label: 'Warning', pulse: false },
  fault: { dot: 'bg-critical-500', label: 'Fault', pulse: false },
};

export default function DeviceCard({ device, active, onClick }: Props) {
  const cfg = statusConfig[device.status] ?? statusConfig.offline;

  return (
    <button
      onClick={onClick}
      className={`text-left rounded-lg border p-4 transition-all duration-200 hover:-translate-y-0.5 ${
        active
          ? 'border-primary-500 bg-primary-50 dark:bg-primary-500/10'
          : 'border-surface-200 dark:border-surface-800 hover:border-surface-400 dark:hover:border-surface-600'
      }`}
    >
      <div className="flex items-center gap-2 mb-1">
        {cfg.pulse ? (
          <span className="relative flex w-2.5 h-2.5">
            <span className={`animate-statusPulse absolute inline-flex h-full w-full rounded-full ${cfg.dot} opacity-75`} />
            <span className={`relative inline-flex rounded-full w-2.5 h-2.5 ${cfg.dot}`} />
          </span>
        ) : (
          <span className={`w-2.5 h-2.5 rounded-full ${cfg.dot}`} />
        )}
        <span className="font-semibold text-sm text-surface-900 dark:text-surface-50">{device.name}</span>
      </div>
      <p className="text-xs text-surface-600 dark:text-surface-400">{device.location ?? 'No location'}</p>
      <p className="text-xs text-surface-400 dark:text-surface-600 mt-1">{cfg.label}</p>
      {device.firmware_version && (
        <p className="text-xs text-surface-400 dark:text-surface-600 mt-1 font-mono">fw {device.firmware_version}</p>
      )}
    </button>
  );
}
