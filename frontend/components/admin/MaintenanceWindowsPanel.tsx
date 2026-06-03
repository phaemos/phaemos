'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';

interface MaintenanceWindow {
  id: string;
  label: string;
  start_at: string;
  end_at: string;
  device_id: string | null;
  suppress_alerts: boolean;
}

const inputClass =
  'w-full rounded bg-white dark:bg-surface-900 border border-surface-200 dark:border-surface-800 px-3 py-2 text-sm text-surface-900 dark:text-surface-50 focus:outline-none focus:border-primary-500';
const labelClass = 'block text-sm text-surface-600 dark:text-surface-400 mb-1';

function fmt(iso: string) {
  return new Date(iso).toLocaleString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function isActive(w: MaintenanceWindow) {
  const now = Date.now();
  return new Date(w.start_at).getTime() <= now && new Date(w.end_at).getTime() >= now;
}

export default function MaintenanceWindowsPanel() {
  const [windows, setWindows] = useState<MaintenanceWindow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  // create form
  const [label, setLabel] = useState('');
  const [startAt, setStartAt] = useState('');
  const [endAt, setEndAt] = useState('');
  const [suppress, setSuppress] = useState(true);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const load = async () => {
    try {
      const res = await api.get<MaintenanceWindow[]>('/maintenance-windows');
      setWindows(res.data);
    } catch {
      setError('Failed to load maintenance windows.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleCreate = async () => {
    setCreateError(null);
    if (!label.trim() || !startAt || !endAt) {
      setCreateError('Label, start and end are required.');
      return;
    }
    if (new Date(endAt) <= new Date(startAt)) {
      setCreateError('End must be after start.');
      return;
    }
    setCreating(true);
    try {
      await api.post('/maintenance-windows', {
        label: label.trim(),
        start_at: new Date(startAt).toISOString(),
        end_at: new Date(endAt).toISOString(),
        suppress_alerts: suppress,
      });
      setLabel('');
      setStartAt('');
      setEndAt('');
      setSuppress(true);
      await load();
    } catch {
      setCreateError('Failed to create window - check the server logs.');
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: string) => {
    setDeleting(id);
    try {
      await api.delete(`/maintenance-windows/${id}`);
      setWindows((prev) => prev.filter((w) => w.id !== id));
    } catch {
      setError('Delete failed.');
    } finally {
      setDeleting(null);
    }
  };

  return (
    <div className="space-y-6">
      {/* Window list */}
      {loading && <p className="text-sm text-surface-500">Loading...</p>}
      {error && <p className="text-sm text-critical-500">{error}</p>}

      {!loading && windows.length === 0 && (
        <p className="text-sm text-surface-500">No maintenance windows scheduled.</p>
      )}

      {windows.length > 0 && (
        <div className="space-y-2">
          {windows.map((w) => {
            const active = isActive(w);
            return (
              <div
                key={w.id}
                className="flex items-start justify-between gap-4 rounded-lg border border-surface-200 dark:border-surface-800 px-4 py-3"
              >
                <div className="space-y-0.5 min-w-0">
                  <div className="flex items-centre gap-2">
                    <span className="text-sm font-medium text-surface-900 dark:text-surface-50 truncate">
                      {w.label}
                    </span>
                    {active && (
                      <span className="shrink-0 text-xs font-medium px-1.5 py-0.5 rounded-full bg-warning-100 dark:bg-warning-900/30 text-warning-700 dark:text-warning-400">
                        Active
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-surface-500">
                    {fmt(w.start_at)} - {fmt(w.end_at)}
                  </p>
                  {!w.suppress_alerts && (
                    <p className="text-xs text-surface-400">Alerts not suppressed</p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => handleDelete(w.id)}
                  disabled={deleting === w.id}
                  className="shrink-0 text-xs text-critical-500 hover:text-critical-600 disabled:opacity-50 transition-colors"
                >
                  {deleting === w.id ? 'Deleting...' : 'Delete'}
                </button>
              </div>
            );
          })}
        </div>
      )}

      {/* Create form */}
      <div className="border-t border-surface-200 dark:border-surface-800 pt-4 space-y-3">
        <p className="text-sm font-medium text-surface-700 dark:text-surface-300">
          Schedule a window
        </p>

        <div>
          <label className={labelClass}>Label</label>
          <input
            type="text"
            placeholder="e.g. Planned firmware upgrade - Node 3"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            className={inputClass}
          />
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className={labelClass}>Start</label>
            <input
              type="datetime-local"
              value={startAt}
              onChange={(e) => setStartAt(e.target.value)}
              className={inputClass}
            />
          </div>
          <div>
            <label className={labelClass}>End</label>
            <input
              type="datetime-local"
              value={endAt}
              onChange={(e) => setEndAt(e.target.value)}
              className={inputClass}
            />
          </div>
        </div>

        <label className="flex items-centre gap-2 text-sm text-surface-600 dark:text-surface-400 cursor-pointer">
          <input
            type="checkbox"
            checked={suppress}
            onChange={(e) => setSuppress(e.target.checked)}
            className="rounded border-surface-300 text-primary-500"
          />
          Suppress alerts during this window
        </label>

        {createError && <p className="text-sm text-critical-500">{createError}</p>}

        <button
          type="button"
          onClick={handleCreate}
          disabled={creating}
          className="bg-brand-600 hover:bg-brand-700 active:scale-95 text-white px-4 py-2 rounded-lg text-sm font-medium transition-all duration-150 disabled:opacity-50"
        >
          {creating ? 'Scheduling...' : 'Schedule window'}
        </button>
      </div>
    </div>
  );
}
