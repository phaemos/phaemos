'use client';

// convert this to a client component so it can use hooks (useState, useEffect,
// useTelemetry) to fetch device data and stream live telemetry.
// in Next.js 15 App Router, params is a Promise even in client components;
// React.use() unwraps it synchronously within the render so the page can read
// the dynamic segment without adding an extra async wrapper.

import PageHeader from '@/components/ui/PageHeader';
import Card from '@/components/ui/Card';
import Link from 'next/link';
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

  // fetch only device metadata here - the latest reading comes from the
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

  // fetch the user list once so the owner picker dropdown is populated.
  // only admins see this picker so this request is skipped for other roles.
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

  // poll GET /telemetry/{id}/latest every 5s and pass data[0] to SensorGrid
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

      <div className="space-y-2">
        <Link href="/devices" className="text-xs font-medium text-surface-500 hover:text-surface-900 dark:text-surface-400 dark:hover:text-surface-100">← Devices</Link>
        <PageHeader
          title={device.name}
          description={`${device.location ?? 'No location'} · ${device.type ?? 'unknown node'}`}
          actions={
            <>
              <StatusBadge status={device.status as 'online' | 'offline' | 'warning' | 'fault'} />
              <a href={`${API_BASE}/api/v1/telemetry/export?device_id=${id}`} download
                className="rounded-lg border border-surface-200 px-3 py-1.5 text-sm font-medium text-surface-700 hover:bg-surface-50 dark:border-surface-700 dark:text-surface-200 dark:hover:bg-surface-800">
                Export CSV
              </a>
            </>
          }
        />
      </div>

      <TelemetryChart deviceId={id} />

      <section aria-labelledby="latest-title" className="space-y-3">
        <h2 id="latest-title" className="text-sm font-semibold text-surface-900 dark:text-surface-50">Latest readings</h2>
        <SensorGrid reading={liveReadings[0] ?? null} />
      </section>

      <Card title="Details" bodyClassName="grid gap-6 p-4 md:grid-cols-2">
        <div>
          <p className="mb-1.5 text-xs font-medium text-surface-500 dark:text-surface-400">Assigned technician</p>
          {isAdmin ? (
            <select aria-label="Assigned technician" value={device.owner_id ?? ''} onChange={(e) => handleOwnerChange(e.target.value)} disabled={savingOwner}
              className="w-full max-w-xs rounded-lg border border-surface-200 bg-white px-3 py-1.5 text-sm text-surface-900 outline-none focus:ring-2 focus:ring-brand-500 disabled:opacity-60 dark:border-surface-700 dark:bg-surface-900 dark:text-surface-50">
              <option value="">Unassigned</option>
              {technicians.map((u) => (
                <option key={u.id} value={u.id}>{u.name ?? u.email}</option>
              ))}
            </select>
          ) : (
            <p className="text-sm text-surface-800 dark:text-surface-200">{technicians.find((u) => u.id === device.owner_id)?.name ?? 'Unassigned'}</p>
          )}
          <p className="mt-3 font-mono text-xs text-surface-500 dark:text-surface-400">ID {id}</p>
        </div>
        <div>
          <p className="mb-1.5 text-xs font-medium text-surface-500 dark:text-surface-400">Tags</p>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-surface-800 dark:text-surface-200">
            {(device.tags ?? []).length === 0 && <span className="text-surface-500 dark:text-surface-400">No tags</span>}
            {(device.tags ?? []).map((tag) => (
              <span key={tag} className="inline-flex items-center gap-1">
                {tag}
                {isAdmin && (
                  <button type="button" onClick={() => handleRemoveTag(tag)} aria-label={`Remove tag ${tag}`}
                    className="text-surface-400 hover:text-critical-600">&times;</button>
                )}
              </span>
            ))}
          </div>
          {isAdmin && (
            <div className="mt-2 flex gap-2">
              <input type="text" placeholder="Add a tag" aria-label="New tag" value={newTag} onChange={(e) => setNewTag(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') handleAddTag(); }}
                className="max-w-xs flex-1 rounded-lg border border-surface-200 bg-white px-3 py-1.5 text-sm text-surface-900 outline-none focus:ring-2 focus:ring-brand-500 dark:border-surface-700 dark:bg-surface-900 dark:text-surface-50" />
              <button type="button" onClick={handleAddTag} disabled={savingTag || !newTag.trim()}
                className="rounded-lg border border-surface-200 px-3 py-1.5 text-sm font-medium text-surface-700 hover:bg-surface-50 disabled:opacity-50 dark:border-surface-700 dark:text-surface-200 dark:hover:bg-surface-800">
                Add
              </button>
            </div>
          )}
        </div>
      </Card>
    </main>
  );
}
