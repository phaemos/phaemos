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

function ScoreBand(score: number): { colour: string; label: string } {
  if (score >= 80) return { colour: 'text-success-400', label: 'Good' };
  if (score >= 50) return { colour: 'text-warning-400', label: 'Degraded' };
  return { colour: 'text-critical-400', label: 'Critical' };
}

interface StatProps {
  label: string;
  value: number | string;
  sub?: string;
  accent?: string;
}

function Stat({ label, value, sub, accent }: StatProps) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-surface-400 uppercase tracking-wide">{label}</span>
      <span className={`text-2xl font-semibold tabular-nums ${accent ?? 'text-surface-100'}`}>
        {value}
      </span>
      {sub && <span className="text-xs text-surface-500">{sub}</span>}
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
    return (
      <div className="rounded-xl border border-surface-800 bg-surface-900 p-5 animate-pulse h-24" />
    );
  }

  const { colour, label } = ScoreBand(data.health_score);

  return (
    <div className="rounded-xl border border-surface-800 bg-surface-900 p-5">
      <div className="flex items-start justify-between mb-5">
        <h2 className="text-sm font-medium text-surface-300 uppercase tracking-wide">
          Fleet health
        </h2>
        <span className={`text-3xl font-bold tabular-nums ${colour}`}>
          {data.health_score}
          <span className="text-base font-normal text-surface-500">%</span>
          <span className={`ml-2 text-xs font-medium ${colour}`}>{label}</span>
        </span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-5">
        <Stat
          label="Online"
          value={data.online}
          sub={`of ${data.total_devices} devices`}
          accent="text-success-400"
        />
        <Stat
          label="Offline"
          value={data.offline}
          accent={data.offline > 0 ? 'text-critical-400' : undefined}
        />
        <Stat
          label="Active alerts"
          value={data.active_alerts}
          accent={data.active_alerts > 0 ? 'text-warning-400' : undefined}
        />
        <Stat
          label="Open tickets"
          value={data.open_tickets}
          accent={data.open_tickets > 0 ? 'text-warning-400' : undefined}
        />
      </div>
    </div>
  );
}
