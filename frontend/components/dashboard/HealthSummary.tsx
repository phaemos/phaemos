'use client';

import { useState, useEffect } from 'react';
import api from '../../lib/api';

interface HealthData {
  total_devices: number;
  online: number;
  offline: number;
  active_alerts: number;
  open_tickets: number;
  health_score: number;
}

function ScoreBand(score: number): { colour: string; bar: string; label: string } {
  // the class names are written out in full because Tailwind only generates classes it can see
  if (score >= 80) return { colour: 'text-success-600 dark:text-success-400', bar: 'bg-success-500', label: 'Good' };
  if (score >= 50) return { colour: 'text-warning-600 dark:text-warning-400', bar: 'bg-warning-500', label: 'Degraded' };
  return { colour: 'text-critical-600 dark:text-critical-400', bar: 'bg-critical-500', label: 'Critical' };
}

interface StatProps {
  label: string;
  value: number | string;
  sub?: string;
  accent?: string;
}

function Stat({ label, value, sub, accent }: StatProps) {
  return (
    <div className="flex flex-col gap-1 p-4">
      <span className="text-xs font-medium text-surface-500 dark:text-surface-400">{label}</span>
      <span className={`text-2xl font-semibold tabular-nums ${accent ?? 'text-surface-900 dark:text-surface-100'}`}>
        {value}
      </span>
      {sub && <span className="text-xs text-surface-600 dark:text-surface-500">{sub}</span>}
    </div>
  );
}

export default function HealthSummary() {
  const [data, setData] = useState<HealthData | null>(null);

  useEffect(() => {
    const load = () =>
      api.get<HealthData>('/health/summary').then(({ data }) => setData(data)).catch(() => null);

    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, []);

  if (!data) {
    return <div className="h-[92px] animate-pulse rounded-lg border border-surface-200 dark:border-surface-800 bg-white dark:bg-surface-900" />;
  }

  const { colour, bar, label } = ScoreBand(data.health_score);

  return (
    <section aria-label="Fleet health" className="grid grid-cols-2 overflow-hidden rounded-lg border border-surface-200 dark:border-surface-800 bg-white dark:bg-surface-900 sm:grid-cols-5 sm:divide-x divide-surface-200 dark:divide-surface-800">
      <div className="col-span-2 border-b border-surface-200 p-4 dark:border-surface-800 sm:col-span-1 sm:border-b-0">
        <span className="text-xs font-medium text-surface-500 dark:text-surface-400">Fleet health</span>
        <p className={`mt-1 text-2xl font-semibold tabular-nums ${colour}`}>
          {data.health_score}%<span className="ml-2 text-xs font-medium">{label}</span>
        </p>
        <div className="mt-2 h-1.5 rounded-full bg-surface-100 dark:bg-surface-800" aria-hidden="true">
          <div className={`h-1.5 rounded-full ${bar}`} style={{ width: `${data.health_score}%` }} />
        </div>
      </div>
      <Stat label="Online" value={data.online} sub={`of ${data.total_devices} machines`} />
      <Stat label="Offline" value={data.offline} accent={data.offline > 0 ? 'text-critical-600 dark:text-critical-400' : undefined} />
      <Stat label="Active alerts" value={data.active_alerts} accent={data.active_alerts > 0 ? 'text-critical-600 dark:text-critical-400' : undefined} />
      <Stat label="Open tickets" value={data.open_tickets} accent={data.open_tickets > 0 ? 'text-warning-600 dark:text-warning-400' : undefined} />
    </section>
  );
}
