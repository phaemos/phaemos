'use client';

// live readings for one device as small multiples: each sensor gets its own chart and scale, since
// pressure near 1000 hPa on the same axis as a 23 degree temperature flattens both into a line.
// The anomaly score comes first with the alert threshold drawn on it.

import { useState, useMemo, useCallback, useRef } from 'react';
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useTelemetry } from '../hooks/useTelemetry';
import { useWebSocketTelemetry } from '../hooks/useWebSocketTelemetry';
import type { Telemetry } from '../types/index';
import Card from './ui/Card';
import Segmented from './ui/Segmented';

type Range = '1h' | '6h' | '24h' | '7d';

const RANGES = [
  { value: '1h', label: '1h', hours: 1 },
  { value: '6h', label: '6h', hours: 6 },
  { value: '24h', label: '24h', hours: 24 },
  { value: '7d', label: '7d', hours: 168 },
] as const;

interface Metric {
  key: keyof Telemetry;
  label: string;
  unit: string;
  colour: string;
  digits: number;
}

// the anomaly model's alert threshold, matching ANOMALY_THRESHOLD in the backend
const THRESHOLD = 0.7;

const SCORE: Metric = { key: 'anomaly_score', label: 'Anomaly score', unit: '', colour: '#ef4444', digits: 2 };

const METRICS: Metric[] = [
  { key: 'vib_magnitude', label: 'Vibration', unit: 'g', colour: '#2563eb', digits: 2 },
  { key: 'temperature', label: 'Temperature', unit: '°C', colour: '#f97316', digits: 1 },
  { key: 'contact_temp', label: 'Contact temperature', unit: '°C', colour: '#ea580c', digits: 1 },
  { key: 'humidity', label: 'Humidity', unit: '%', colour: '#0ea5e9', digits: 1 },
  { key: 'moisture_level', label: 'Moisture', unit: '', colour: '#0284c7', digits: 0 },
  { key: 'current_ma', label: 'Current', unit: 'mA', colour: '#16a34a', digits: 0 },
  { key: 'pressure', label: 'Pressure', unit: 'hPa', colour: '#8b5cf6', digits: 1 },
  { key: 'gas_level', label: 'Gas', unit: '', colour: '#a16207', digits: 0 },
  { key: 'fft_peak_hz', label: 'Vibration peak', unit: 'Hz', colour: '#1d4ed8', digits: 1 },
  { key: 'light_level', label: 'Light', unit: '', colour: '#ca8a04', digits: 0 },
];

interface Props {
  deviceId: string;
  nodeType?: string;
  // one chart per row, for narrow columns such as the comparison view
  compact?: boolean;
}

function fromTsForRange(range: Range): string {
  const hours = RANGES.find((r) => r.value === range)!.hours;
  return new Date(Date.now() - hours * 3_600_000).toISOString();
}

export default function TelemetryChart({ deviceId, nodeType, compact = false }: Props) {
  const [range, setRange] = useState<Range>('1h');
  const fromTs = useMemo(() => fromTsForRange(range), [range]);

  const { data: polledReadings, loading } = useTelemetry(deviceId, { fromTs, limit: 500, nodeType });

  // readings pushed over the WebSocket since the last poll, newest first
  const liveRef = useRef<Telemetry[]>([]);
  const handleWsMessage = useCallback((reading: Telemetry) => {
    liveRef.current = [reading, ...liveRef.current].slice(0, 50);
  }, []);
  useWebSocketTelemetry(deviceId, { onMessage: handleWsMessage });

  const readings = useMemo(() => {
    const seen = new Set(polledReadings.map((r) => r.id));
    // the buffer is read during render on purpose: it is refreshed with each poll rather than
    // re-rendering on every WebSocket message
    // eslint-disable-next-line react-hooks/refs
    const fresh = liveRef.current.filter((r) => !seen.has(r.id));
    return [...fresh, ...polledReadings];
  }, [polledReadings]);

  const data = useMemo(() => {
    const ordered = [...readings].reverse();
    return ordered.map((r, i) => {
      // a rolling mean of the last 10 scores: one flagged reading is expected now and then,
      // a rising average is the trend worth acting on
      const window = ordered.slice(Math.max(0, i - 9), i + 1).map((x) => x.anomaly_score).filter((v): v is number => v != null);
      return {
        ...r,
        score_trend: window.length ? window.reduce((a, b) => a + b, 0) / window.length : null,
        time: new Date(r.recorded_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }),
      };
    });
  }, [readings]);

  const shown = METRICS.filter((m) => readings.some((r) => r[m.key] !== null && r[m.key] !== undefined));
  const hasScore = readings.some((r) => r.anomaly_score !== null && r.anomaly_score !== undefined);

  return (
    <Card
      title="Live readings"
      description={loading ? 'Loading readings…' : `${readings.length} readings in the last ${range}`}
      actions={<Segmented label="Time range" options={RANGES} value={range} onChange={setRange} />}
    >
      {!hasScore && shown.length === 0 && !loading ? (
        <p className="py-10 text-center text-sm text-surface-500 dark:text-surface-400">No readings in this time range.</p>
      ) : (
        <div className={`grid gap-3 ${compact ? '' : 'sm:grid-cols-2 xl:grid-cols-3'}`}>
          {hasScore && <MetricChart metric={SCORE} data={data} threshold={THRESHOLD} wide={!compact} />}
          {shown.map((m) => <MetricChart key={m.key as string} metric={m} data={data} />)}
        </div>
      )}
    </Card>
  );
}

type Row = Telemetry & { time: string; score_trend: number | null };

function MetricChart({ metric, data, threshold, wide }: { metric: Metric; data: Row[]; threshold?: number; wide?: boolean }) {
  const key = metric.key as string;
  const latest = [...data].reverse().find((r) => r[metric.key] !== null && r[metric.key] !== undefined)?.[metric.key] as number | undefined;
  const alarming = threshold !== undefined && latest !== undefined && latest >= threshold;
  const gradient = `fill-${key}`;
  return (
    <div className={`rounded-md border border-surface-200 dark:border-surface-800 p-3 ${wide ? 'sm:col-span-2 xl:col-span-3' : ''}`}>
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-xs font-medium text-surface-500 dark:text-surface-400">
          {metric.label}
          {threshold !== undefined && <span className="ml-2 font-normal">faint: each reading, solid: 10-reading average</span>}
        </h3>
        <p className={`font-mono text-sm font-semibold tabular-nums ${alarming ? 'text-critical-600 dark:text-critical-400' : 'text-surface-900 dark:text-surface-50'}`}>
          {latest === undefined ? '-' : latest.toFixed(metric.digits)}
          {metric.unit && <span className="ml-0.5 text-xs font-normal text-surface-500">{metric.unit}</span>}
          {alarming && <span className="ml-2 text-xs font-medium">Above threshold</span>}
        </p>
      </div>
      <div className={wide ? 'h-36' : 'h-28'}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={metric.colour} stopOpacity={0.25} />
                <stop offset="100%" stopColor={metric.colour} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} strokeOpacity={0.15} stroke="currentColor" />
            <XAxis dataKey="time" tick={{ fontSize: 10 }} stroke="currentColor" strokeOpacity={0.4} tickLine={false} axisLine={false} minTickGap={40} />
            <YAxis tick={{ fontSize: 10 }} stroke="currentColor" strokeOpacity={0.4} tickLine={false} axisLine={false} width={48} tickFormatter={(v: number) => (Math.abs(v) >= 100 ? v.toFixed(0) : String(Number(v.toFixed(2))))}
              domain={threshold !== undefined ? [0, 1] : ['auto', 'auto']} />
            <Tooltip
              contentStyle={{ fontSize: 11, borderRadius: 6 }}
              formatter={(v, name) => [typeof v === 'number' ? `${v.toFixed(metric.digits)}${metric.unit ? ' ' + metric.unit : ''}` : v, name]}
            />
            {threshold !== undefined && (
              <ReferenceLine y={threshold} stroke="#ef4444" strokeDasharray="4 4" label={{ value: 'alert threshold', fontSize: 10, position: 'insideTopRight', fill: '#ef4444' }} />
            )}
            <Area type="monotone" dataKey={key} stroke={metric.colour} strokeWidth={threshold !== undefined ? 1 : 1.5} strokeOpacity={threshold !== undefined ? 0.35 : 1}
              fill={`url(#${gradient})`} dot={false} connectNulls isAnimationActive={false} name={metric.label} />
            {threshold !== undefined && (
              <Area type="monotone" dataKey="score_trend" stroke={metric.colour} strokeWidth={2} fill="none" dot={false} connectNulls isAnimationActive={false} name="10-reading average" />
            )}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
