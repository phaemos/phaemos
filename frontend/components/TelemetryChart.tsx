'use client';

// I split readings into sensor groups so each chart has a focused y-axis scale
// instead of cramming incompatible units (Celsius, g-units, mA) onto one axis.

import { useState, useMemo, useCallback, useRef } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { useTelemetry } from '../hooks/useTelemetry';
import { useWebSocketTelemetry } from '../hooks/useWebSocketTelemetry';
import type { Telemetry } from '../types/index';

type Range = '1h' | '6h' | '24h' | '7d';

const RANGE_LABELS: { value: Range; label: string; hours: number }[] = [
  { value: '1h', label: '1h', hours: 1 },
  { value: '6h', label: '6h', hours: 6 },
  { value: '24h', label: '24h', hours: 24 },
  { value: '7d', label: '7d', hours: 168 },
];

interface SensorGroup {
  label: string;
  keys: (keyof Telemetry)[];
  colours: string[];
}

const SENSOR_GROUPS: SensorGroup[] = [
  {
    label: 'Environmental',
    keys: ['temperature', 'humidity', 'pressure'],
    colours: ['#F59E0B', '#3B82F6', '#A78BFA'],
  },
  {
    label: 'Vibration',
    keys: ['vibration_x', 'vibration_y', 'vibration_z', 'vib_magnitude'],
    colours: ['#10B981', '#F87171', '#60A5FA', '#FBBF24'],
  },
  {
    label: 'Power',
    keys: ['bus_voltage', 'current_ma', 'power_mw'],
    colours: ['#34D399', '#F472B6', '#FB923C'],
  },
  {
    label: 'Surface & Distance',
    keys: ['ir_temperature', 'contact_temp', 'distance_mm'],
    colours: ['#EF4444', '#6366F1', '#22D3EE'],
  },
];

interface Props {
  deviceId: string;
  nodeType?: string;
}

function fromTsForRange(range: Range): string {
  const hours = RANGE_LABELS.find((r) => r.value === range)!.hours;
  return new Date(Date.now() - hours * 3_600_000).toISOString();
}

function hasData(readings: Telemetry[], keys: (keyof Telemetry)[]): boolean {
  return readings.some((r) => keys.some((k) => r[k] !== null && r[k] !== undefined));
}

export default function TelemetryChart({ deviceId, nodeType }: Props) {
  const [range, setRange] = useState<Range>('1h');

  const fromTs = useMemo(() => fromTsForRange(range), [range]);

  // I limit to 500 rows for the historical view — enough to draw smooth lines
  // without saturating the browser paint cycle.
  const { data: polledReadings, loading } = useTelemetry(deviceId, { fromTs, limit: 500, nodeType });

  // I keep WS-pushed readings in a ref to avoid re-renders on every push.
  // The chart only rebuilds when polledReadings changes (every 5s poll), but
  // the ref lets me merge live readings in the useMemo below without stale closures.
  const liveRef = useRef<Telemetry[]>([]);

  const handleWsMessage = useCallback((reading: Telemetry) => {
    // I cap the live buffer at 50 entries so unbounded device activity does not
    // grow memory without limit between polling cycles.
    liveRef.current = [reading, ...liveRef.current].slice(0, 50);
  }, []);

  useWebSocketTelemetry(deviceId, { onMessage: handleWsMessage });

  // I merge live readings ahead of polled ones; duplicates are filtered by id
  // so a reading that arrives via WS before the next poll does not appear twice.
  const readings = useMemo(() => {
    const seen = new Set(polledReadings.map((r) => r.id));
    const fresh = liveRef.current.filter((r) => !seen.has(r.id));
    return [...fresh, ...polledReadings];
  }, [polledReadings]);

  const chartData = useMemo(
    () =>
      [...readings]
        .reverse()
        .map((r) => ({
          time: new Date(r.recorded_at).toLocaleTimeString('en-GB', {
            hour: '2-digit',
            minute: '2-digit',
          }),
          ...Object.fromEntries(
            SENSOR_GROUPS.flatMap((g) => g.keys).map((k) => [k, r[k]]),
          ),
        })),
    [readings],
  );

  const visibleGroups = SENSOR_GROUPS.filter((g) => hasData(readings, g.keys));

  return (
    <div className="space-y-4">
      {/* Time range selector */}
      <div className="flex items-centre gap-1">
        {RANGE_LABELS.map(({ value, label }) => (
          <button
            key={value}
            type="button"
            onClick={() => setRange(value)}
            className={`px-3 py-1 rounded text-xs font-medium transition-colours ${
              range === value
                ? 'bg-brand-600 text-white'
                : 'bg-surface-100 dark:bg-surface-800 text-surface-600 dark:text-surface-400 hover:bg-surface-200 dark:hover:bg-surface-700 hover:text-surface-800 dark:hover:text-surface-200'
            }`}
          >
            {label}
          </button>
        ))}
        {loading && (
          <span className="ml-3 text-xs text-surface-400 dark:text-surface-600 animate-pulse">Loading...</span>
        )}
      </div>

      {visibleGroups.length === 0 && !loading && (
        <p className="text-sm text-surface-400 dark:text-surface-600 py-8 text-centre">
          No telemetry in this time range.
        </p>
      )}

      {visibleGroups.map((group) => (
        <SensorGroupChart key={group.label} group={group} data={chartData} />
      ))}
    </div>
  );
}

interface GroupChartProps {
  group: SensorGroup;
  data: Record<string, string | number | null | undefined>[];
}

function SensorGroupChart({ group, data }: GroupChartProps) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="rounded-xl border border-surface-200 dark:border-surface-800 bg-surface-50 dark:bg-surface-900/40 overflow-hidden">
      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="w-full flex items-centre justify-between px-4 py-2.5 text-left hover:bg-surface-100 dark:hover:bg-white/5 transition-colours"
      >
        <span className="text-xs font-semibold text-surface-600 dark:text-surface-400 uppercase tracking-wider">
          {group.label}
        </span>
        <span className="text-surface-400 dark:text-surface-600 text-xs">{collapsed ? '+' : '-'}</span>
      </button>

      {!collapsed && (
        <div className="px-4 pb-4">
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#9CA3AF' }} />
              <YAxis tick={{ fontSize: 10, fill: '#9CA3AF' }} width={42} />
              <Tooltip
                contentStyle={{ background: '#111827', border: '1px solid #374151', fontSize: 11 }}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {group.keys.map((key, i) => (
                <Line
                  key={key as string}
                  type="monotone"
                  dataKey={key as string}
                  stroke={group.colours[i] ?? '#9CA3AF'}
                  dot={false}
                  strokeWidth={1.5}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
