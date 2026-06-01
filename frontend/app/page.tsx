'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';
import type { Device, Alert } from '@/types';
import DeviceCard from '@/components/DeviceCard';
import AlertBanner from '@/components/AlertBanner';
import TelemetryChart from '@/components/TelemetryChart';

export default function DashboardPage() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [selected, setSelected] = useState<string | null>(null);

  // I poll devices and active alerts every 5 seconds - they change infrequently
  // so polling is fine. Only telemetry gets the real-time WebSocket treatment.
  useEffect(() => {
    const load = async () => {
      const [devRes, alertRes] = await Promise.all([
        api.get<Device[]>('/devices'),
        api.get<Alert[]>('/alerts?resolved=false'),
      ]);
      setDevices(devRes.data);
      setAlerts(alertRes.data);
      if (devRes.data.length > 0 && !selected) {
        setSelected(devRes.data[0].id);
      }
    };
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <main className="p-6 max-w-7xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">PHAEMOS Dashboard</h1>

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
            onClick={() => setSelected(d.id)}
          />
        ))}
      </div>

      {/* TelemetryChart manages its own time-range fetch - just pass the selected device id. */}
      {selected && <TelemetryChart deviceId={selected} />}
    </main>
  );
}
