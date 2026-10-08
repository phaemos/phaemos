'use client';

// fetch the device list once on mount so users can pick from named devices
// rather than typing raw UUIDs. The chart columns are driven by the selected IDs.

import PageHeader from '@/components/ui/PageHeader';
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
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <PageHeader title="Compare" description={`Pick up to ${MAX_COMPARE} machines to see their readings side by side.`} />

      <div role="group" aria-label="Machines to compare" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {devices.map((d) => {
          const active = selected.includes(d.id);
          const disabled = !active && selected.length >= MAX_COMPARE;
          return (
            <button
              key={d.id}
              type="button"
              aria-pressed={active}
              onClick={() => toggle(d.id)}
              disabled={disabled}
              className={`rounded-lg border bg-white p-3 text-left transition-colors dark:bg-surface-900 ${
                active
                  ? 'border-brand-500 ring-1 ring-brand-500'
                  : disabled
                  ? 'cursor-not-allowed border-surface-200 opacity-50 dark:border-surface-800'
                  : 'border-surface-200 hover:border-surface-300 dark:border-surface-800 dark:hover:border-surface-700'
              }`}
            >
              <span className="flex items-center justify-between gap-2">
                <span className="truncate text-sm font-semibold text-surface-900 dark:text-surface-50">{d.name}</span>
                <span className={`h-4 w-4 shrink-0 rounded border ${active ? 'border-brand-600 bg-brand-600' : 'border-surface-300 dark:border-surface-600'}`} aria-hidden="true">
                  {active && <svg viewBox="0 0 16 16" className="h-4 w-4 text-white" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M4 8.5l2.5 2.5L12 5.5" /></svg>}
                </span>
              </span>
              <span className="mt-1 block text-xs text-surface-500 dark:text-surface-400">{d.location ?? 'No location'}</span>
            </button>
          );
        })}
      </div>

      {selected.length === 0 && (
        <p className="text-sm text-surface-500 dark:text-surface-400">No machines picked yet. Choose two or three above to compare them.</p>
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
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-sm font-semibold text-surface-800 dark:text-surface-200">{device?.name ?? deviceId}</h2>
                    <p className="text-xs text-surface-500 dark:text-surface-400">{device?.location ?? 'No location'}</p>
                  </div>
                  <StatusBadge status={(device?.status ?? 'offline') as 'online' | 'offline' | 'warning' | 'fault'} />
                </div>
                <TelemetryChart deviceId={deviceId} compact />
              </div>
            );
          })}
        </div>
      )}
    </main>
  );
}
