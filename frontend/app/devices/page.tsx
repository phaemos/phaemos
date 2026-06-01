'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';
import type { Device } from '@/types';

export default function DevicesPage() {
  const [devices, setDevices] = useState<Device[]>([]);

  useEffect(() => {
    api.get<Device[]>('/devices').then((r) => setDevices(r.data));
  }, []);

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
    </main>
  );
}
