'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';
import type { Device, Alert } from '@/types';
import DeviceCard from '@/components/DeviceCard';
import AlertBanner from '@/components/AlertBanner';
import TelemetryChart from '@/components/TelemetryChart';

const NODE_TYPES = ['all', 'esp32', 'stm32', 'pico_w', 'nano'] as const;

export default function DashboardPage() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [nodeType, setNodeType] = useState<string>('all');
  // I track whether the user has manually picked a device so polling never
  // auto-selects the first device and overrides their choice.
  const [userSelected, setUserSelected] = useState(false);

  // I poll devices and active alerts every 5 seconds - they change infrequently
  // so polling is fine. Only telemetry gets the real-time WebSocket treatment.
  useEffect(() => {
    const load = async () => {
      // I use allSettled so a failing alerts query never blocks device cards from rendering.
      const [devResult, alertResult] = await Promise.allSettled([
        api.get<Device[]>('/devices'),
        api.get<Alert[]>('/alerts?resolved=false'),
      ]);
      if (devResult.status === 'fulfilled') {
        setDevices(devResult.value.data);
        // I only auto-select the first device on the very first load, never on
        // subsequent polls - otherwise the selection resets every 5 seconds.
        setSelected((prev) => {
          if (prev || userSelected) return prev;
          return devResult.value.data[0]?.id ?? null;
        });
      }
      if (alertResult.status === 'fulfilled') {
        setAlerts(alertResult.value.data);
      }
    };
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, [userSelected]);

  const activeNodeType = nodeType === 'all' ? undefined : nodeType;

  return (
    <main className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-centre justify-between">
        <h1 className="text-2xl font-bold tracking-tight">PHAEMOS Dashboard</h1>

        {/* Node type filter — narrows which readings are fetched for the chart */}
        <div className="flex items-centre gap-1">
          {NODE_TYPES.map((nt) => (
            <button
              key={nt}
              type="button"
              onClick={() => setNodeType(nt)}
              className={`px-3 py-1 rounded text-xs font-medium transition-colours ${
                nodeType === nt
                  ? 'bg-brand-600 text-white'
                  : 'bg-surface-100 dark:bg-surface-800 text-surface-600 dark:text-surface-400 hover:bg-surface-200 dark:hover:bg-surface-700 hover:text-surface-800 dark:hover:text-surface-200'
              }`}
            >
              {nt}
            </button>
          ))}
        </div>
      </div>

      {alerts.length > 0 && (
        <div className="space-y-2">
          {alerts.slice(0, 3).map((a) => (
            <AlertBanner key={a.id} alert={a} />
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {devices.map((d) => (
          <DeviceCard
            key={d.id}
            device={d}
            active={selected === d.id}
            onClick={() => { setSelected(d.id); setUserSelected(true); }}
          />
        ))}
      </div>

      {/* TelemetryChart manages its own fetch - pass device id and optional node type filter. */}
      {selected && <TelemetryChart deviceId={selected} nodeType={activeNodeType} />}
    </main>
  );
}
