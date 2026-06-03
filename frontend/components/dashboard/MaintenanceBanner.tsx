'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';

interface MaintenanceWindow {
  id: string;
  label: string;
  end_at: string;
}

// I poll every 60s - maintenance windows change rarely so tight polling is wasteful.
const POLL_MS = 60_000;

export default function MaintenanceBanner() {
  const [active, setActive] = useState<MaintenanceWindow | null>(null);

  useEffect(() => {
    const check = async () => {
      try {
        const res = await api.get<MaintenanceWindow[]>('/maintenance-windows');
        const now = Date.now();
        const current = res.data.find(
          (w) => new Date(w.end_at).getTime() >= now,
        ) ?? null;
        setActive(current);
      } catch {
        // I silently ignore errors - a failing banner check must never break the dashboard.
      }
    };
    check();
    const id = setInterval(check, POLL_MS);
    return () => clearInterval(id);
  }, []);

  if (!active) return null;

  return (
    <div className="rounded-lg border border-warning-300 dark:border-warning-700 bg-warning-50 dark:bg-warning-900/20 px-4 py-3 flex items-centre gap-3">
      <span className="shrink-0 w-2 h-2 rounded-full bg-warning-500 animate-pulse mt-0.5" />
      <p className="text-sm text-warning-800 dark:text-warning-300">
        <span className="font-semibold">Maintenance in progress:</span> {active.label}
        {' - '}alerts suppressed until{' '}
        {new Date(active.end_at).toLocaleString('en-GB', {
          day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
        })}
      </p>
    </div>
  );
}
