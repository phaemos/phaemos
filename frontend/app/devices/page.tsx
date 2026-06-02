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
    online: 'bg-green-500',
    offline: 'bg-gray-400',
    warning: 'bg-yellow-500',
    fault: 'bg-red-500',
  };

  return (
    <main className="p-6 max-w-5xl mx-auto space-y-4">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Devices</h1>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {devices.map((d) => (
          <div key={d.id} className="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-transparent p-4 space-y-1">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${statusDot[d.status] ?? 'bg-gray-400'}`} />
              <span className="font-semibold text-gray-900 dark:text-gray-100">{d.name}</span>
            </div>
            <p className="text-sm text-gray-500 dark:text-gray-400">{d.location ?? 'No location set'}</p>
            <p className="text-xs text-gray-400 dark:text-gray-500 uppercase tracking-wide">
              {d.type ?? 'Unknown type'}
            </p>
            <p className="text-xs text-gray-400 dark:text-gray-500">
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
          className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 disabled:opacity-40 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
        >
          Previous
        </button>
        <span className="text-sm text-gray-500 dark:text-gray-400">Page {page}</span>
        <button
          type="button"
          disabled={devices.length < PAGE_SIZE}
          onClick={() => setPage((p) => p + 1)}
          className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 disabled:opacity-40 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
        >
          Next
        </button>
      </div>
    </main>
  );
}
