'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';
import type { Alert } from '@/types';

const severityColor: Record<string, string> = {
  info: 'border-primary-500 dark:border-primary-500 bg-primary-50 dark:bg-primary-500/10 text-primary-700 dark:text-primary-100',
  warning: 'border-warning-500 dark:border-warning-500 bg-warning-50 dark:bg-warning-500/10 text-warning-600 dark:text-warning-100',
  critical: 'border-critical-500 dark:border-critical-500 bg-critical-50 dark:bg-critical-500/10 text-critical-600 dark:text-critical-100',
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
      <h1 className="text-2xl font-bold text-surface-900 dark:text-surface-50">Alerts</h1>
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
              className="text-sm px-3 py-1 rounded bg-white/60 dark:bg-surface-800 hover:bg-white dark:hover:bg-surface-700 border border-current/20"
            >
              Resolve
            </button>
          )}
        </div>
      ))}
    </main>
  );
}
