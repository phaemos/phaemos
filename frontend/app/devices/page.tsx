'use client';

import { useEffect, useState, useCallback } from 'react';
import api from '@/lib/api';
import type { Device } from '@/types';
import EmptyState from '@/components/ui/EmptyState';
import LoadingSkeleton from '@/components/ui/LoadingSkeleton';
import { useToast } from '@/hooks/useToast';

function getTokenRole(): string | null {
  if (typeof window === 'undefined') return null;
  const token = localStorage.getItem('token');
  if (!token) return null;
  try {
    return JSON.parse(atob(token.split('.')[1])).role ?? null;
  } catch { return null; }
}

const PAGE_SIZE = 20;

const STATUS_TABS = [
  { label: 'All', value: '' },
  { label: 'Online', value: 'online' },
  { label: 'Offline', value: 'offline' },
  { label: 'Warning', value: 'warning' },
  { label: 'Fault', value: 'fault' },
];

const STATUS_DOT: Record<string, string> = {
  online:  'bg-success-500',
  offline: 'bg-surface-400',
  warning: 'bg-warning-500',
  fault:   'bg-critical-500',
};

export default function DevicesPage() {
  const { addToast } = useToast();
  const [devices, setDevices]     = useState<Device[]>([]);
  const [loading, setLoading]     = useState(true);
  const [page, setPage]           = useState(1);
  const [search, setSearch]       = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [statusFilter, setStatus] = useState('');

  // batch firmware update
  const [selected, setSelected]     = useState<Set<string>>(new Set());
  const [showModal, setShowModal]   = useState(false);
  const [batchTag, setBatchTag]     = useState('');
  const [batchVersion, setBatchVersion] = useState('');
  const [batching, setBatching]     = useState(false);
  const isAdmin = typeof window !== 'undefined' && getTokenRole() === 'admin';

  // I debounce the search so the API is not hit on every keystroke.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  const load = useCallback(() => {
    setLoading(true);
    const params: Record<string, string | number> = {
      skip: (page - 1) * PAGE_SIZE,
      limit: PAGE_SIZE,
    };
    if (debouncedSearch) params.search = debouncedSearch;
    if (statusFilter)    params.status = statusFilter;
    api
      .get<Device[]>('/devices', { params })
      .then((r) => setDevices(r.data))
      .finally(() => setLoading(false));
  }, [page, debouncedSearch, statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  // Reset to page 1 when filters change.
  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, statusFilter]);

  const toggleSelect = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) { next.delete(id); } else { next.add(id); }
      return next;
    });

  const toggleAll = () =>
    setSelected(selected.size === devices.length ? new Set() : new Set(devices.map((d) => d.id)));

  const handleBatchFirmware = async () => {
    if (!batchTag.trim() || !batchVersion.trim()) return;
    setBatching(true);
    try {
      const res = await api.post<{ queued: number }>('/devices/batch/firmware-update', {
        tag: batchTag.trim(),
        version: batchVersion.trim(),
      });
      addToast('success', `Queued firmware ${batchVersion} for ${res.data.queued} device(s) tagged "${batchTag}"`);
      setShowModal(false);
      setBatchTag('');
      setBatchVersion('');
      setSelected(new Set());
    } catch {
      addToast('error', 'Batch firmware update failed');
    } finally {
      setBatching(false);
    }
  };

  return (
    <main className="p-6 max-w-5xl mx-auto space-y-4">
      <h1 className="text-2xl font-bold text-surface-900 dark:text-surface-50">Devices</h1>

      {/* Search */}
      <input
        type="search"
        placeholder="Search devices..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full max-w-sm px-3 py-2 rounded-lg border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 text-sm text-surface-900 dark:text-surface-50 focus:ring-2 focus:ring-brand-500 outline-none"
      />

      {/* Status filter tabs */}
      <div className="flex gap-1 flex-wrap">
        {STATUS_TABS.map((tab) => (
          <button
            key={tab.value}
            type="button"
            onClick={() => setStatus(tab.value)}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-colours duration-150 ${
              statusFilter === tab.value
                ? 'bg-brand-600 text-white'
                : 'bg-surface-100 dark:bg-surface-800 text-surface-600 dark:text-surface-400 hover:bg-surface-200 dark:hover:bg-surface-700'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {loading ? (
        <LoadingSkeleton />
      ) : devices.length === 0 ? (
        <EmptyState
          icon="📡"
          heading="No devices found"
          subMessage={
            debouncedSearch || statusFilter
              ? 'Try clearing your filters.'
              : 'Register a device to get started.'
          }
        />
      ) : (
        <>
          {/* Select-all row - admins only */}
          {isAdmin && (
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-2 text-sm text-surface-600 dark:text-surface-400 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={selected.size === devices.length && devices.length > 0}
                  onChange={toggleAll}
                  className="rounded border-surface-300 text-brand-600"
                />
                Select all
              </label>
              {selected.size > 0 && (
                <button
                  type="button"
                  onClick={() => setShowModal(true)}
                  className="bg-brand-600 hover:bg-brand-700 text-white px-3 py-1 rounded-lg text-xs font-medium transition-colours"
                >
                  Bulk firmware update ({selected.size})
                </button>
              )}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {devices.map((d) => (
              <div key={d.id} className="relative">
                {isAdmin && (
                  <input
                    type="checkbox"
                    checked={selected.has(d.id)}
                    onChange={() => toggleSelect(d.id)}
                    onClick={(e) => e.stopPropagation()}
                    className="absolute top-3 right-3 z-10 rounded border-surface-300 text-brand-600 cursor-pointer"
                    aria-label={`Select ${d.name}`}
                  />
                )}
                <a
                  href={`/devices/${d.id}`}
                  className={`card p-4 space-y-1 block hover:-translate-y-0.5 transition-all duration-200 ${selected.has(d.id) ? 'ring-2 ring-brand-500' : ''}`}
                >
                  <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${STATUS_DOT[d.status] ?? 'bg-surface-400'}`} />
                    <span className="font-semibold text-surface-900 dark:text-surface-50">{d.name}</span>
                  </div>
                  <p className="text-sm text-surface-600 dark:text-surface-400">{d.location ?? 'No location set'}</p>
                  <p className="text-xs text-surface-400 dark:text-surface-600 uppercase tracking-wide">
                    {d.type ?? 'Unknown type'}
                  </p>
                  <p className="text-xs text-surface-400 dark:text-surface-600">
                    Last seen: {d.last_seen ? new Date(d.last_seen).toLocaleString() : 'Never'}
                  </p>
                  {d.tags && d.tags.length > 0 && (
                    <div className="flex flex-wrap gap-1 pt-1">
                      {d.tags.map((tag) => (
                        <span key={tag} className="bg-brand-50 dark:bg-brand-900/20 text-brand-600 dark:text-brand-400 text-xs px-2 py-0.5 rounded-full">
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                </a>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Bulk firmware update modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white dark:bg-surface-900 rounded-xl border border-surface-200 dark:border-surface-800 p-6 w-full max-w-sm mx-4 space-y-4">
            <h2 className="text-base font-semibold text-surface-900 dark:text-surface-50">Bulk Firmware Update</h2>
            <p className="text-sm text-surface-600 dark:text-surface-400">
              Updates all devices with the given tag. Devices pick up the new version on next boot.
            </p>
            <div className="space-y-3">
              <div>
                <label className="block text-sm text-surface-600 dark:text-surface-400 mb-1">Tag</label>
                <input
                  type="text"
                  placeholder="e.g. production"
                  value={batchTag}
                  onChange={(e) => setBatchTag(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 text-sm text-surface-900 dark:text-surface-50 focus:ring-2 focus:ring-brand-500 outline-none"
                />
              </div>
              <div>
                <label className="block text-sm text-surface-600 dark:text-surface-400 mb-1">Target version</label>
                <input
                  type="text"
                  placeholder="e.g. 1.2.0"
                  value={batchVersion}
                  onChange={(e) => setBatchVersion(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 text-sm text-surface-900 dark:text-surface-50 focus:ring-2 focus:ring-brand-500 outline-none"
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowModal(false)}
                className="px-4 py-2 rounded-lg text-sm font-medium bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700 text-surface-900 dark:text-surface-50 transition-colours"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleBatchFirmware}
                disabled={batching || !batchTag.trim() || !batchVersion.trim()}
                className="px-4 py-2 rounded-lg text-sm font-medium bg-brand-600 hover:bg-brand-700 text-white transition-colours disabled:opacity-50"
              >
                {batching ? 'Updating...' : 'Update'}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between pt-2">
        <button
          type="button"
          disabled={page === 1}
          onClick={() => setPage((p) => p - 1)}
          className="bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700 text-surface-900 dark:text-surface-50 px-4 py-2 rounded-lg text-sm font-medium transition-colours duration-150 disabled:opacity-40"
        >
          Previous
        </button>
        <span className="text-sm text-surface-600 dark:text-surface-400">Page {page}</span>
        <button
          type="button"
          disabled={devices.length < PAGE_SIZE}
          onClick={() => setPage((p) => p + 1)}
          className="bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700 text-surface-900 dark:text-surface-50 px-4 py-2 rounded-lg text-sm font-medium transition-colours duration-150 disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </main>
  );
}
