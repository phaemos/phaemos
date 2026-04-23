'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';
import type { Device, Telemetry, Alert } from '@/types';
import DeviceCard from '@/components/DeviceCard';
import AlertBanner from '@/components/AlertBanner';
import TelemetryChart from '@/components/TelemetryChart';

export default function DashboardPage() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [readings, setReadings] = useState<Telemetry[]>([]);

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

  useEffect(() => {
    if (!selected) return;
    const load = async () => {
      const res = await api.get<Telemetry[]>(`/telemetry/${selected}?limit=50`);
      setReadings(res.data.reverse());
    };
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, [selected]);

  return (
    <main className="p-6 max-w-7xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">PulseWatch Dashboard</h1>

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

      {selected && readings.length > 0 && <TelemetryChart readings={readings} />}
    </main>
  );
}
