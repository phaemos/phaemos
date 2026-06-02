'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';
import type { Device } from '@/types';

const PAGE_SIZE = 20;

export default function DevicesPage() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [page, setPage] = useState(1);

  useEffect(() => {
    api
      .get<Device[]>('/devices', { params: { skip: (page - 1) * PAGE_SIZE, limit: PAGE_SIZE } })
      .then((r) => setDevices(r.data));
  }, [page]);

  const statusDot: Record<string, string> = {
    online: 'bg-success-500',
    offline: 'bg-surface-400',
    warning: 'bg-warning-500',
    fault: 'bg-critical-500',
  };

  return (
    <main className="p-6 max-w-5xl mx-auto space-y-4">
      <h1 className="text-2xl font-bold text-surface-900 dark:text-surface-50">Devices</h1>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {devices.map((d) => (
          <div key={d.id} className="rounded-lg border border-surface-200 dark:border-surface-800 bg-white dark:bg-transparent p-4 space-y-1">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${statusDot[d.status] ?? 'bg-surface-400'}`} />
              <span className="font-semibold text-surface-900 dark:text-surface-50">{d.name}</span>
            </div>
            <p className="text-sm text-surface-600 dark:text-surface-400">{d.location ?? 'No location set'}</p>
            <p className="text-xs text-surface-400 dark:text-surface-600 uppercase tracking-wide">
              {d.type ?? 'Unknown type'}
            </p>
            <p className="text-xs text-surface-400 dark:text-surface-600">
              Last seen:{' '}
              {d.last_seen ? new Date(d.last_seen).toLocaleString() : 'Never'}
            </p>
          </div>
        ))}
      </div>

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
