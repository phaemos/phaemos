'use client';

// I fetch the device list once on mount so users can pick from named devices
// rather than typing raw UUIDs. The chart columns are driven by the selected IDs.

import { useState, useEffect } from 'react';
import api from '@/lib/api';
import type { Device } from '@/types';
import TelemetryChart from '@/components/TelemetryChart';
import StatusBadge from '@/components/ui/StatusBadge';

const MAX_COMPARE = 3;

export default function ComparePage() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get<Device[]>('/devices')
      .then((res) => setDevices(res.data))
      .finally(() => setLoading(false));
  }, []);

  const toggle = (id: string) => {
    setSelected((prev) =>
      prev.includes(id)
        ? prev.filter((s) => s !== id)
        : prev.length < MAX_COMPARE
        ? [...prev, id]
        : prev,
    );
  };

  if (loading) {
    return (
      <main className="p-6 max-w-7xl mx-auto">
        <p className="text-surface-400 dark:text-surface-600 text-sm">Loading devices...</p>
      </main>
    );
  }

  return (
    <main className="p-6 max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-surface-900 dark:text-surface-50">Device Comparison</h1>
        <p className="text-sm text-surface-600 dark:text-surface-400 mt-1">
          Select up to {MAX_COMPARE} devices to compare their telemetry side by side.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {devices.map((d) => {
          const active = selected.includes(d.id);
          const disabled = !active && selected.length >= MAX_COMPARE;
          return (
            <button
              key={d.id}
              type="button"
              onClick={() => toggle(d.id)}
              disabled={disabled}
              className={`flex items-centre gap-2 px-3 py-1.5 rounded-lg border text-sm transition-colours ${
                active
                  ? 'border-primary-500 bg-primary-50 dark:bg-primary-500/10 text-primary-700 dark:text-primary-200'
                  : disabled
                  ? 'border-surface-200 dark:border-surface-800 bg-surface-50 dark:bg-surface-900/20 text-surface-400 cursor-not-allowed'
                  : 'border-surface-200 dark:border-surface-800 bg-surface-50 dark:bg-surface-900/40 text-surface-800 dark:text-surface-400 hover:border-surface-400 dark:hover:border-surface-400 hover:text-surface-900 dark:hover:text-surface-50'
              }`}
            >
              <StatusBadge status={d.status as 'online' | 'offline' | 'warning' | 'fault'} />
              {d.name}
            </button>
          );
        })}
      </div>

      {selected.length === 0 && (
        <p className="text-surface-400 dark:text-surface-600 text-sm">No devices selected. Pick one above to start comparing.</p>
      )}

      {selected.length > 0 && (
        <div
          className="grid gap-6"
          style={{ gridTemplateColumns: `repeat(${selected.length}, minmax(0, 1fr))` }}
        >
          {selected.map((deviceId) => {
            const device = devices.find((d) => d.id === deviceId);
            return (
              <div key={deviceId} className="space-y-3">
                <div className="flex items-centre justify-between">
                  <div>
                    <h2 className="text-sm font-semibold text-surface-800 dark:text-surface-200">{device?.name ?? deviceId}</h2>
                    <p className="text-xs text-surface-400 dark:text-surface-600">{device?.location ?? 'No location'}</p>
                  </div>
                  <StatusBadge status={(device?.status ?? 'offline') as 'online' | 'offline' | 'warning' | 'fault'} />
                </div>
                <TelemetryChart deviceId={deviceId} />
              </div>
            );
          })}
        </div>
      )}
    </main>
  );
}
