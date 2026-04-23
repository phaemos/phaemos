'use client';

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
import type { Telemetry } from '@/types';

interface Props {
  readings: Telemetry[];
}

export default function TelemetryChart({ readings }: Props) {
  const data = readings.map((r) => ({
    time: new Date(r.recorded_at).toLocaleTimeString(),
    temperature: r.temperature,
    humidity: r.humidity,
    vibration_x: r.vibration_x,
  }));

  return (
    <div className="rounded-lg border border-gray-800 p-4 bg-gray-900/40">
      <h2 className="text-sm font-semibold text-gray-300 mb-4">Live Telemetry</h2>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis dataKey="time" tick={{ fontSize: 11, fill: '#9CA3AF' }} />
          <YAxis tick={{ fontSize: 11, fill: '#9CA3AF' }} />
          <Tooltip
            contentStyle={{ background: '#111827', border: '1px solid #374151' }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Line
            type="monotone"
            dataKey="temperature"
            stroke="#F59E0B"
            dot={false}
            strokeWidth={2}
          />
          <Line
            type="monotone"
            dataKey="humidity"
            stroke="#3B82F6"
            dot={false}
            strokeWidth={2}
          />
          <Line
            type="monotone"
            dataKey="vibration_x"
            stroke="#10B981"
            dot={false}
            strokeWidth={2}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
