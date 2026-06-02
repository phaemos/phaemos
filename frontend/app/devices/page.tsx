'use client';

import { useEffect, useState, useCallback } from 'react';
import api from '@/lib/api';
import type { Device } from '@/types';
import EmptyState from '@/components/ui/EmptyState';
import LoadingSkeleton from '@/components/ui/LoadingSkeleton';

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
  const [devices, setDevices]     = useState<Device[]>([]);
  const [loading, setLoading]     = useState(true);
  const [page, setPage]           = useState(1);
  const [search, setSearch]       = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [statusFilter, setStatus] = useState('');

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
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {devices.map((d) => (
            <a
              key={d.id}
              href={`/devices/${d.id}`}
              className="card p-4 space-y-1 block hover:-translate-y-0.5 transition-all duration-200"
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
          ))}
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
