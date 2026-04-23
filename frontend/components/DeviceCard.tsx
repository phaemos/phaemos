import type { Device } from '@/types';

interface Props {
  device: Device;
  active: boolean;
  onClick: () => void;
}

const statusConfig: Record<string, { dot: string; label: string }> = {
  online: { dot: 'bg-green-500', label: 'Online' },
  offline: { dot: 'bg-gray-500', label: 'Offline' },
  warning: { dot: 'bg-yellow-500', label: 'Warning' },
  fault: { dot: 'bg-red-500', label: 'Fault' },
};

export default function DeviceCard({ device, active, onClick }: Props) {
  const cfg = statusConfig[device.status] ?? statusConfig.offline;

  return (
    <button
      onClick={onClick}
      className={`text-left rounded-lg border p-4 transition-colors ${
        active
          ? 'border-blue-500 bg-blue-950/30'
          : 'border-gray-800 hover:border-gray-600'
      }`}
    >
      <div className="flex items-center gap-2 mb-1">
        <span className={`w-2 h-2 rounded-full ${cfg.dot}`} />
        <span className="font-semibold text-sm">{device.name}</span>
      </div>
      <p className="text-xs text-gray-400">{device.location ?? 'No location'}</p>
      <p className="text-xs text-gray-500 mt-1">{cfg.label}</p>
    </button>
  );
}
