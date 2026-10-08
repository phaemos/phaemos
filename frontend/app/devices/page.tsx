'use client';

import { useEffect, useState, useCallback } from 'react';
import api from '@/lib/api';
import type { Device } from '@/types';
import EmptyState from '@/components/ui/EmptyState';
import LoadingSkeleton from '@/components/ui/LoadingSkeleton';
import { useToast } from '@/hooks/useToast';
import Card from '@/components/ui/Card';
import PageHeader from '@/components/ui/PageHeader';
import Segmented from '@/components/ui/Segmented';

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
] as const;

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
  const [statusFilter, setStatus] = useState<(typeof STATUS_TABS)[number]['value']>('');

  // batch firmware update
  const [selected, setSelected]     = useState<Set<string>>(new Set());
  const [showModal, setShowModal]   = useState(false);
  const [batchTag, setBatchTag]     = useState('');
  const [batchVersion, setBatchVersion] = useState('');
  const [batching, setBatching]     = useState(false);
  const isAdmin = typeof window !== 'undefined' && getTokenRole() === 'admin';

  // debounce the search so the API is not hit on every keystroke.
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
    // fetching on mount/dependency change, the documented effect pattern
    // (react.dev/learn/synchronizing-with-effects#fetching-data).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  // reset to page 1 when filters change.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
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
    <main className="mx-auto max-w-6xl space-y-6 p-6">
      <PageHeader
        title="Devices"
        description="Every registered machine, its node and when it last reported."
        actions={
          <>
            <input
              type="search"
              placeholder="Search machines"
              aria-label="Search machines"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-56 rounded-lg border border-surface-200 bg-white px-3 py-1.5 text-sm text-surface-900 outline-none focus:ring-2 focus:ring-brand-500 dark:border-surface-700 dark:bg-surface-900 dark:text-surface-50"
            />
            <Segmented label="Status" options={STATUS_TABS} value={statusFilter} onChange={setStatus} />
          </>
        }
      />

      <Card bodyClassName="">
        {loading ? (
          <div className="p-4"><LoadingSkeleton /></div>
        ) : devices.length === 0 ? (
          <EmptyState
            heading="No machines found"
            subMessage={debouncedSearch || statusFilter ? 'Try clearing the search or the status filter.' : 'Register a device to get started.'}
          />
        ) : (
          <>
            {isAdmin && selected.size > 0 && (
              <div className="flex items-center justify-between border-b border-surface-200 bg-surface-50 px-4 py-2 text-sm dark:border-surface-800 dark:bg-surface-900/60">
                <span className="text-surface-600 dark:text-surface-300">{selected.size} selected</span>
                <button type="button" onClick={() => setShowModal(true)} className="rounded-md bg-brand-600 px-3 py-1 text-xs font-medium text-white hover:bg-brand-700">
                  Bulk firmware update
                </button>
              </div>
            )}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-surface-500 dark:text-surface-400">
                  <tr className="border-b border-surface-200 dark:border-surface-800">
                    {isAdmin && (
                      <th scope="col" className="w-10 px-4 py-2.5">
                        <input type="checkbox" checked={selected.size === devices.length && devices.length > 0} onChange={toggleAll}
                          aria-label="Select all machines" className="rounded border-surface-300 text-brand-600" />
                      </th>
                    )}
                    <th scope="col" className="px-4 py-2.5 font-medium">Machine</th>
                    <th scope="col" className="px-4 py-2.5 font-medium">Node</th>
                    <th scope="col" className="px-4 py-2.5 font-medium">Status</th>
                    <th scope="col" className="px-4 py-2.5 font-medium">Last seen</th>
                    <th scope="col" className="px-4 py-2.5 font-medium">Tags</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-200 dark:divide-surface-800">
                  {devices.map((d) => (
                    <tr key={d.id} className={`hover:bg-surface-50 dark:hover:bg-surface-800/40 ${selected.has(d.id) ? 'bg-brand-50/60 dark:bg-brand-500/10' : ''}`}>
                      {isAdmin && (
                        <td className="px-4 py-3">
                          <input type="checkbox" checked={selected.has(d.id)} onChange={() => toggleSelect(d.id)}
                            aria-label={`Select ${d.name}`} className="rounded border-surface-300 text-brand-600" />
                        </td>
                      )}
                      <td className="px-4 py-3">
                        <a href={`/devices/${d.id}`} className="font-medium text-surface-900 hover:text-brand-600 dark:text-surface-50 dark:hover:text-brand-400">{d.name}</a>
                        <p className="text-xs text-surface-500 dark:text-surface-400">{d.location ?? 'No location set'}</p>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-surface-600 dark:text-surface-300">{d.type ?? '-'}</td>
                      <td className="px-4 py-3">
                        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-surface-700 dark:text-surface-300">
                          <span className={`h-2 w-2 rounded-full ${STATUS_DOT[d.status] ?? 'bg-surface-400'}`} aria-hidden="true" />
                          {STATUS_TABS.find((t) => t.value === d.status)?.label ?? d.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-surface-500 dark:text-surface-400">
                        {d.last_seen ? new Date(d.last_seen).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : 'Never'}
                      </td>
                      <td className="px-4 py-3 text-xs text-surface-500 dark:text-surface-400">{d.tags?.length ? d.tags.join(', ') : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Card>

      {/* bulk firmware update modal */}
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
                className="px-4 py-2 rounded-lg text-sm font-medium bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700 text-surface-900 dark:text-surface-50 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleBatchFirmware}
                disabled={batching || !batchTag.trim() || !batchVersion.trim()}
                className="px-4 py-2 rounded-lg text-sm font-medium bg-brand-600 hover:bg-brand-700 text-white transition-colors disabled:opacity-50"
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
          className="bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700 text-surface-900 dark:text-surface-50 px-4 py-2 rounded-lg text-sm font-medium transition-colors duration-150 disabled:opacity-40"
        >
          Previous
        </button>
        <span className="text-sm text-surface-600 dark:text-surface-400">Page {page}</span>
        <button
          type="button"
          disabled={devices.length < PAGE_SIZE}
          onClick={() => setPage((p) => p + 1)}
          className="bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700 text-surface-900 dark:text-surface-50 px-4 py-2 rounded-lg text-sm font-medium transition-colors duration-150 disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </main>
  );
}
