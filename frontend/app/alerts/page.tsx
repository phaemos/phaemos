'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';
import type { Alert } from '@/types';

const severityColor: Record<string, string> = {
  info: 'border-blue-500 bg-blue-950/30',
  warning: 'border-yellow-500 bg-yellow-950/30',
  critical: 'border-red-500 bg-red-950/30',
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
      <h1 className="text-2xl font-bold">Alerts</h1>
      {alerts.map((a) => (
        <div
          key={a.id}
          className={`border rounded-lg p-4 flex items-start justify-between gap-4 ${severityColor[a.severity ?? 'info']}`}
        >
          <div>
            <p className="font-medium capitalize">
              {a.severity} - {a.message}
            </p>
            <p className="text-sm text-gray-400">
              {new Date(a.triggered_at).toLocaleString()}
            </p>
          </div>
          {!a.resolved && (
            <button
              onClick={() => resolve(a.id)}
              className="text-sm px-3 py-1 rounded bg-gray-700 hover:bg-gray-600"
            >
              Resolve
            </button>
          )}
        </div>
      ))}
    </main>
  );
}
