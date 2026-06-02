'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';
import type { Alert } from '@/types';

const severityColor: Record<string, string> = {
  info: 'border-blue-400 dark:border-blue-500 bg-blue-50 dark:bg-blue-950/30 text-blue-800 dark:text-blue-100',
  warning: 'border-yellow-400 dark:border-yellow-500 bg-yellow-50 dark:bg-yellow-950/30 text-yellow-800 dark:text-yellow-100',
  critical: 'border-red-400 dark:border-red-500 bg-red-50 dark:bg-red-950/30 text-red-800 dark:text-red-100',
};

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[]>([]);

  const load = () => api.get<Alert[]>('/alerts').then((r) => setAlerts(r.data));

  useEffect(() => {
    load();
  }, []);

  const resolve = async (id: string) => {
    await api.patch(`/alerts/${id}/resolve`);
    load();
  };

  return (
    <main className="p-6 max-w-4xl mx-auto space-y-4">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Alerts</h1>
      {alerts.map((a) => (
        <div
          key={a.id}
          className={`border rounded-lg p-4 flex items-start justify-between gap-4 ${severityColor[a.severity ?? 'info']}`}
        >
          <div>
            <p className="font-medium capitalize">
              {a.severity} - {a.message}
            </p>
            <p className="text-sm opacity-70">
              {new Date(a.triggered_at).toLocaleString()}
            </p>
          </div>
          {!a.resolved && (
            <button
              onClick={() => resolve(a.id)}
              className="text-sm px-3 py-1 rounded bg-white/60 dark:bg-gray-700 hover:bg-white dark:hover:bg-gray-600 border border-current/20"
            >
              Resolve
            </button>
          )}
        </div>
      ))}
    </main>
  );
}
