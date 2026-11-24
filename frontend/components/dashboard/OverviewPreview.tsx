// the overview rendered from fixed sample data, for the public home page. It makes no requests and has no live
// controls: the same presentational pieces as the dashboard, fed from this file. Readings are plausible for the
// sensors in docs/sensor_reference.md (BME280 temperature and humidity, MPU6050 vibration after FFT).

import DeviceCard from '@/components/DeviceCard';
import Panel from '@/components/ui/Panel';
import { countBySeverity } from '@/lib/alertGroups';
import { sortAlerts } from '@/lib/alertLife';
import { countFleet, linkOf } from '@/lib/machineState';
import type { Alert, Device } from '@/types';
import NeedsAttention from './NeedsAttention';
import ReadingChart, { type ChartRow } from './ReadingChart';
import StatStrip, { type HealthData } from './StatStrip';

// a fixed clock so every relative time reads the same on every visit
const NOW = Date.parse('2026-06-10T14:30:00Z');
const minutesAgo = (m: number) => new Date(NOW - m * 60_000).toISOString();

const PUMP = '00000000-0000-4000-8000-0000000000a1';
const COLD = '00000000-0000-4000-8000-0000000000b2';

// alerts as the API returns them: one long-lived row for a machine and a rule, with how long the condition held and how many readings met it
function alert(device: string, metric: string, severity: Alert['severity'], limit: number, latest: number, peak: number, readings: number, heldMinutesAgo: number, seenMinutesAgo: number): Alert {
  const name = device === PUMP ? 'Walk Pump 1' : 'Cold Store 2';
  return {
    id: `${device}-${metric}`,
    device_id: device,
    rule_id: `${metric}-rule`,
    message: `${metric} is ${peak} (gt ${limit}) on ${name}`,
    severity,
    category: 'machine',
    kind: 'rule',
    resolved: false,
    first_seen_at: minutesAgo(heldMinutesAgo),
    triggered_at: minutesAgo(heldMinutesAgo - 1),
    last_seen_at: minutesAgo(seenMinutesAgo),
    still_occurring: seenMinutesAgo <= 2,
    occurrences: readings,
    last_value: latest,
    peak_value: peak,
    resolved_at: null,
  };
}

const ALERTS: Alert[] = [
  alert(PUMP, 'vib_magnitude', 'critical', 1.5, 1.84, 1.84, 210, 36, 0),
  alert(PUMP, 'temperature', 'warning', 30, 38.672, 38.7, 1140, 95, 0),
  alert(COLD, 'humidity', 'warning', 70, 69.4, 78.4, 480, 140, 12),
];

// both machines posted a few seconds before NOW, so their link is online. Their state comes from the same rule the real overview
// uses (lib/machineState.ts) and the strip's counts are worked out from them, so the sample cannot disagree with itself.
const sample = (id: string, name: string, location: string, type: string, secondsAgo: number): Device => ({
  id, name, location, type, status: 'online', link_state: 'online', expected_interval_s: 5, seconds_since_last_post: secondsAgo,
  last_seen: new Date(NOW - secondsAgo * 1000).toISOString(), firmware_version: null, tags: null, owner_id: null, created_at: minutesAgo(9000),
});

const DEVICES: Device[] = [sample(PUMP, 'Walk Pump 1', 'Plant room', 'esp32', 6), sample(COLD, 'Cold Store 2', 'Warehouse, bay 3', 'pico_w', 11)];

const SPLIT = countFleet(DEVICES, ALERTS, NOW);
const HEALTH: HealthData = {
  total_devices: DEVICES.length,
  online: DEVICES.filter((d) => linkOf(d, NOW) === 'online').length,
  offline: DEVICES.filter((d) => linkOf(d, NOW) === 'offline').length,
  active_alerts: ALERTS.length,
  open_tickets: 2,
  health_score: 0,
};

const READINGS = {
  [PUMP]: [
    { key: 'temperature', label: 'Temperature', value: '38.7', unit: '°C' },
    { key: 'vib_magnitude', label: 'Vibration', value: '1.84', unit: 'g' },
    { key: 'current_ma', label: 'Current', value: '412', unit: 'mA' },
  ],
  [COLD]: [
    { key: 'temperature', label: 'Temperature', value: '4.1', unit: '°C' },
    { key: 'humidity', label: 'Humidity', value: '78', unit: '%' },
    { key: 'pressure', label: 'Pressure', value: '1009', unit: 'hPa' },
  ],
};

// a slow rise with a little ripple, written as arithmetic so the chart is the same on every render. One reading every 2.5 minutes
// for the last hour, drawn against real time like the live chart.
const STEP_MS = 150_000;
const CHART: ChartRow[] = Array.from({ length: 24 }, (_, i) => ({ t: NOW - (23 - i) * STEP_MS, temperature: i === 23 ? 38.7 : 31 + i * 0.33 + Math.sin(i * 1.3) * 0.5 }));
// the last point is the figure on the machine's card above, so the chart and the card agree
const WINDOW = { start: NOW - 3_600_000, end: NOW };

export default function OverviewPreview() {
  const alerts = sortAlerts(ALERTS);
  return (
    <div className="space-y-4">
      <StatStrip data={HEALTH} severity={countBySeverity(ALERTS)} split={SPLIT} />
      <NeedsAttention
        alerts={alerts}
        deviceNames={{ [PUMP]: 'Walk Pump 1', [COLD]: 'Cold Store 2' }}
        alertCount={ALERTS.length}
        interactive={false}
        now={NOW}
      />
      <div className="grid gap-3 sm:grid-cols-2">
        {DEVICES.map((d, i) => (
          <DeviceCard key={d.id} device={d} active={i === 0} readings={READINGS[d.id as keyof typeof READINGS]} alerts={ALERTS} now={NOW} />
        ))}
      </div>
      <Panel title="Live readings" description="Walk Pump 1, last hour" bodyClassName="p-3">
        <ReadingChart metric={{ key: 'temperature', label: 'Temperature', unit: '°C', digits: 1 }} data={CHART} window={WINDOW} intervalMs={STEP_MS} />
      </Panel>
    </div>
  );
}
