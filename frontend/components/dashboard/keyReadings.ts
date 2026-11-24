import type { Telemetry } from '../../types/index';
import { currentReading, type Fault } from '../../lib/machineState';

export interface KeyReading {
  // the telemetry field, so a page can tell which sensor produced it
  key: string;
  label: string;
  value: string;
  unit: string;
  // set when the field has no current value: the faulted or quiet sensor's reason in words. The card then reads "No reading".
  noReading?: string;
}

// the order a machine's headline readings are chosen in: the first three that the data actually holds
const KEY_FIELDS: { key: keyof Telemetry; label: string; unit: string; digits: number }[] = [
  { key: 'temperature', label: 'Temperature', unit: '°C', digits: 1 },
  { key: 'vib_magnitude', label: 'Vibration', unit: 'g', digits: 2 },
  { key: 'humidity', label: 'Humidity', unit: '%', digits: 0 },
  { key: 'current_ma', label: 'Current', unit: 'mA', digits: 0 },
  { key: 'pressure', label: 'Pressure', unit: 'hPa', digits: 0 },
  { key: 'contact_temp', label: 'Contact temp', unit: '°C', digits: 1 },
];

interface Options {
  max?: number;
  // the fields a fault or a not fitted mark stops
  faulted?: ReadonlyMap<string, Pick<Fault, 'name' | 'words' | 'state'>>;
  intervalS?: number;
  now?: number;
}

// readings arrive newest first and each node type sends only its own fields. A field reads as its newest value only while that
// value is current (currentReading decides, as it does for the charts and the readings table). A field that is faulted or has
// gone quiet reads "No reading" with its reason and is not replaced by an older number.
export function keyReadingsFrom(readings: readonly Telemetry[], { max = 3, faulted, intervalS, now }: Options = {}): KeyReading[] {
  const out: KeyReading[] = [];
  for (const f of KEY_FIELDS) {
    if (out.length >= max) break;
    const present = readings.some((r) => typeof r[f.key] === 'number') || faulted?.has(f.key);
    if (!present) continue;
    const c = currentReading(readings, f.key, { fault: faulted?.get(f.key) ?? null, intervalS, now });
    if (c.status === 'value' && typeof c.value === 'number') out.push({ key: f.key, label: f.label, value: c.value.toFixed(f.digits), unit: f.unit });
    else out.push({ key: f.key, label: f.label, value: '', unit: f.unit, noReading: c.reason ?? 'no current value' });
  }
  return out;
}
