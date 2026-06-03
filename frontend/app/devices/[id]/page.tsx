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
import { useToast } from '../../../hooks/useToast';

interface PageProps {
  params: Promise<{ id: string }>;
}

interface UserSummary {
  id: string;
  name: string | null;
  email: string;
  role: string;
}

function getTokenRole(): string | null {
  if (typeof window === 'undefined') return null;
  const token = localStorage.getItem('token');
  if (!token) return null;
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    return payload.role ?? null;
  } catch {
    return null;
  }
}

export default function DeviceDetailPage({ params }: PageProps) {
  const { id } = use(params);
  const { addToast } = useToast();

  const [device, setDevice]   = useState<Device | null>(null);
  const [devErr, setDevErr]   = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [users, setUsers]     = useState<UserSummary[]>([]);
  const [savingOwner, setSavingOwner] = useState(false);
  const [newTag, setNewTag]           = useState('');
  const [savingTag, setSavingTag]     = useState(false);

  const isAdmin = getTokenRole() === 'admin';

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

  // I fetch the user list once so the owner picker dropdown is populated.
  // Only admins see this picker so this request is skipped for other roles.
  useEffect(() => {
    if (!isAdmin) return;
    api.get<UserSummary[]>('/auth/users').then((r) => setUsers(r.data));
  }, [isAdmin]);

  const handleOwnerChange = async (ownerId: string) => {
    setSavingOwner(true);
    try {
      const res = await api.patch<Device>(`/devices/${id}`, {
        owner_id: ownerId === '' ? null : ownerId,
      });
      setDevice(res.data);
      addToast('success', 'Device owner updated');
    } catch {
      addToast('error', 'Failed to update device owner');
    } finally {
      setSavingOwner(false);
    }
  };

  const handleAddTag = async () => {
    const tag = newTag.trim().toLowerCase().replace(/\s+/g, '-');
    if (!tag || !device) return;
    setSavingTag(true);
    try {
      const res = await api.post<Device>(`/devices/${id}/tags`, { tag });
      setDevice(res.data);
      setNewTag('');
    } catch {
      addToast('error', 'Failed to add tag');
    } finally {
      setSavingTag(false);
    }
  };

  const handleRemoveTag = async (tag: string) => {
    if (!device) return;
    try {
      const res = await api.delete<Device>(`/devices/${id}/tags/${encodeURIComponent(tag)}`);
      setDevice(res.data);
    } catch {
      addToast('error', 'Failed to remove tag');
    }
  };

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

  const technicians = users.filter((u) => u.role === 'technician');

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

      {/* Owner picker - admins only */}
      {isAdmin && (
        <section className="card p-4">
          <label className="text-xs font-semibold uppercase tracking-widest text-surface-400 dark:text-surface-500 mb-2 block">
            Assigned Owner
          </label>
          <select
            aria-label="Device owner"
            value={device.owner_id ?? ''}
            onChange={(e) => handleOwnerChange(e.target.value)}
            disabled={savingOwner}
            className="w-full max-w-xs px-3 py-2 rounded-lg border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 text-sm text-surface-900 dark:text-surface-50 focus:ring-2 focus:ring-brand-500 outline-none disabled:opacity-60"
          >
            <option value="">Unassigned</option>
            {technicians.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name ?? u.email}
              </option>
            ))}
          </select>
        </section>
      )}

      {/* Tags - admins can add and remove; all roles see the chips */}
      <section className="card p-4 space-y-3">
        <label className="text-xs font-semibold uppercase tracking-widest text-surface-400 dark:text-surface-500 block">
          Tags
        </label>
        <div className="flex flex-wrap gap-2 min-h-[1.5rem]">
          {(device.tags ?? []).length === 0 && (
            <span className="text-xs text-surface-400 dark:text-surface-600">No tags</span>
          )}
          {(device.tags ?? []).map((tag) => (
            <span
              key={tag}
              className="inline-flex items-centre gap-1 bg-brand-50 dark:bg-brand-900/20 text-brand-600 dark:text-brand-400 text-xs px-2 py-0.5 rounded-full"
            >
              {tag}
              {isAdmin && (
                <button
                  type="button"
                  onClick={() => handleRemoveTag(tag)}
                  className="ml-0.5 hover:text-brand-800 dark:hover:text-brand-200 leading-none"
                  aria-label={`Remove tag ${tag}`}
                >
                  &times;
                </button>
              )}
            </span>
          ))}
        </div>
        {isAdmin && (
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="new-tag"
              value={newTag}
              onChange={(e) => setNewTag(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleAddTag(); }}
              className="flex-1 max-w-xs px-3 py-1.5 rounded-lg border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 text-sm text-surface-900 dark:text-surface-50 focus:ring-2 focus:ring-brand-500 outline-none"
            />
            <button
              type="button"
              onClick={handleAddTag}
              disabled={savingTag || !newTag.trim()}
              className="bg-brand-600 hover:bg-brand-700 text-white px-3 py-1.5 rounded-lg text-sm font-medium transition-colours disabled:opacity-50"
            >
              Add
            </button>
          </div>
        )}
      </section>

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
