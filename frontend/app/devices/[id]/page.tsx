'use client';

// I convert this to a client component so I can use hooks (useState, useEffect,
// useTelemetry) to fetch device data and stream live telemetry.
// In Next.js 15 App Router, params is a Promise even in client components;
// React.use() unwraps it synchronously within the render so the page can read
// the dynamic segment without adding an extra async wrapper.

import { use, useState, useEffect } from 'react';
import type { Device } from '../../../types/index';
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

  const [device, setDevice] = useState<Device | null>(null);
  const [devErr, setDevErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // I fetch only device metadata here - the latest reading comes from the
  // useTelemetry poll below so the sensor grid auto-updates every 5 seconds.
  useEffect(() => {
    api.get<Device>(`/devices/${id}`)
      .then((res) => { setDevice(res.data); })
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : 'Failed to load device';
        setDevErr(message);
      })
      .finally(() => setLoading(false));
  }, [id]);

  // I poll GET /telemetry/{id}/latest every 5s and pass data[0] to SensorGrid
  // so operators see live readings without a page refresh.
  const { data: liveReadings } = useTelemetry(id, { limit: 1 }, 5000);

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
        <p className="text-surface-400 dark:text-surface-600 text-sm">Device not found.</p>
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
          <h1 className="text-xl font-semibold text-surface-900 dark:text-surface-50">{device.name}</h1>
          <p className="text-sm text-surface-600 dark:text-surface-400 mt-0.5">
            {device.location ?? 'No location'} &middot;{' '}
            <span className="font-mono text-xs text-surface-400 dark:text-surface-600">{device.type ?? 'unknown'}</span>
          </p>
          <p className="text-xs text-surface-400 dark:text-surface-600 mt-1 font-mono">{id}</p>
        </div>
        <StatusBadge
          status={device.status as 'online' | 'offline' | 'warning' | 'fault'}
        />
      </div>

      {/* Latest sensor readings grid */}
      <section>
        <h2 className="text-sm font-medium text-surface-600 dark:text-surface-400 mb-3 uppercase tracking-wider">
          Live Sensor Readings
        </h2>
        <SensorGrid reading={liveReadings[0] ?? null} />
      </section>

      {/* Historical telemetry chart */}
      <section>
        <div className="flex items-centre justify-between mb-3">
          <h2 className="text-sm font-medium text-surface-600 dark:text-surface-400 uppercase tracking-wider">
            Telemetry History
          </h2>
          <a
            href={`${API_BASE}/api/v1/telemetry/export?device_id=${id}`}
            download
            className="bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700 text-surface-900 dark:text-surface-50 px-4 py-2 rounded-lg text-sm font-medium transition-colours duration-150"
          >
            Export CSV
          </a>
        </div>
        <TelemetryChart deviceId={id} />
      </section>
    </main>
  );
}
