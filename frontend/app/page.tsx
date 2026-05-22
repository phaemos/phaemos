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

  // I open a WebSocket for live telemetry - the chart updates the instant a reading arrives.
  useEffect(() => {
    if (!selected) return;

    // I load the last 50 readings on initial device selection so the chart isn't empty.
    api.get<Telemetry[]>(`/telemetry/${selected}?limit=50`).then((res) => {
      setReadings(res.data.reverse());
    });

    // I derive the WebSocket base URL from the HTTP API URL by swapping the protocol.
    const apiBase = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
    const wsBase = apiBase.replace(/^http/, 'ws');
    const ws = new WebSocket(`${wsBase}/ws/telemetry/${selected}`);

    ws.onmessage = (event) => {
      const newReading: Telemetry = JSON.parse(event.data);
      // I keep a rolling window of 50 readings to avoid unbounded memory growth.
      setReadings((prev) => [...prev.slice(-49), newReading]);
    };

    // I close cleanly on error - the browser will not auto-reconnect.
    ws.onerror = () => ws.close();

    return () => ws.close();
  }, [selected]);

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

      {selected && readings.length > 0 && <TelemetryChart readings={readings} />}
    </main>
  );
}
