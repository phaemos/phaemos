'use client';

// I convert this to a client component so I can use hooks (useState, useEffect,
// useTelemetry) to fetch device data and stream live telemetry.
// In Next.js 15 App Router, params is a Promise even in client components;
// React.use() unwraps it synchronously within the render so the page can read
// the dynamic segment without adding an extra async wrapper.

import { use, useState, useEffect } from 'react';
import type { Device, Telemetry } from '../../../types/index';
import api from '../../../lib/api';
import { useTelemetry } from '../../../hooks/useTelemetry';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
import SensorGrid from '../../../components/dashboard/SensorGrid';
import TelemetryChart from '../../../components/TelemetryChart';
import StatusBadge from '../../../components/ui/StatusBadge';
import LoadingSkeleton from '../../../components/ui/LoadingSkeleton';
import ErrorToast from '../../../components/ui/ErrorToast';

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function DeviceDetailPage({ params }: PageProps) {
  const { id } = use(params);

  const [device, setDevice]   = useState<Device | null>(null);
  const [latest, setLatest]   = useState<Telemetry | null>(null);
  const [devErr, setDevErr]   = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // I fetch device metadata and the latest single reading in parallel so the
  // page header and sensor grid populate together rather than sequentially.
  useEffect(() => {
    Promise.all([
      api.get<Device>(`/devices/${id}`),
      api.get<Telemetry>(`/telemetry/${id}/latest`).catch(() => null),
    ])
      .then(([devRes, telRes]) => {
        setDevice(devRes.data);
        setLatest(telRes?.data ?? null);
      })
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : 'Failed to load device';
        setDevErr(message);
      })
      .finally(() => setLoading(false));
  }, [id]);

  // I poll the latest reading every 5s so the sensor grid stays live without
  // a full page refresh. TelemetryChart manages its own time-range fetch.
  useTelemetry(id, { limit: 1 });

  if (loading) {
    return (
      <main className="p-6 max-w-7xl mx-auto">
        <LoadingSkeleton />
      </main>
    );
  }

  if (!device) {
    return (
      <main className="p-6 max-w-7xl mx-auto">
        {devErr && (
          <ErrorToast message={devErr} onDismiss={() => setDevErr(null)} />
        )}
        <p className="text-gray-500 text-sm">Device not found.</p>
      </main>
    );
  }

  return (
    <main className="p-6 max-w-7xl mx-auto space-y-6">
      {devErr && (
        <ErrorToast message={devErr} onDismiss={() => setDevErr(null)} />
      )}

      {/* Device header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-100">{device.name}</h1>
          <p className="text-sm text-gray-400 mt-0.5">
            {device.location ?? 'No location'} &middot;{' '}
            <span className="font-mono text-xs text-gray-500">{device.type ?? 'unknown'}</span>
          </p>
          <p className="text-xs text-gray-600 mt-1 font-mono">{id}</p>
        </div>
        <StatusBadge
          status={device.status as 'online' | 'offline' | 'warning' | 'fault'}
        />
      </div>

      {/* Latest sensor readings grid */}
      <section>
        <h2 className="text-sm font-medium text-gray-400 mb-3 uppercase tracking-wider">
          Live Sensor Readings
        </h2>
        <SensorGrid reading={latest} />
      </section>

      {/* Historical telemetry chart - manages its own time range and polling */}
      <section>
        <div className="flex items-centre justify-between mb-3">
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
            Telemetry History
          </h2>
          <a
            href={`${API_BASE}/api/v1/telemetry/export?device_id=${id}`}
            download
            className="px-3 py-1 rounded text-xs font-medium bg-gray-800 text-gray-300 hover:bg-gray-700 hover:text-white transition-colours"
          >
            Export CSV
          </a>
        </div>
        <TelemetryChart deviceId={id} />
      </section>
    </main>
  );
}
