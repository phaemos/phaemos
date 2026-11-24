// reads the words of an alert and names its readings. An alert is one long-lived row (the API keeps one open alert per machine
// and rule), so nothing here groups rows any more. The API returns the metric, the comparison and the threshold only inside the
// message text, so they are parsed back out. Parsing fails soft: a message that does not match is shown unchanged.

export type Severity = 'info' | 'warning' | 'critical';
export type Comparison = 'gt' | 'lt' | 'gte' | 'lte' | 'eq';

// the fields of an API alert that sorting, filtering and counting need
export interface AlertInput {
  id: string;
  device_id: string;
  rule_id: string | null;
  message: string | null;
  severity: Severity | null;
  // 'machine' or 'monitoring'. Absent from an older API, which only has machine alerts.
  category?: string | null;
  triggered_at: string;
  // the sensor a monitoring alert is about
  sensor_key?: string | null;
  // what the system raised the alert for: offline, reset_loop, unscored, sensor or clipping. Null for a rule or model alert.
  kind?: string | null;
}

export interface ParsedAlertMessage {
  // the telemetry column for a rule alert or "anomaly" for one raised by the model
  metric: string;
  // NaN for a model alert whose message carries no figure
  value: number;
  comparison: Comparison | null;
  threshold: number | null;
  deviceName: string | null;
}

const NUMBER = '(-?\\d+(?:\\.\\d+)?(?:[eE][-+]?\\d+)?)';
// written by evaluate_rules in backend/app/services/alert_service.py
// the API adds a closing note to the message when the alert ends, "(resolved: back inside the limit)" or "(closed: ...)"
const ENDING = String.raw`(?: \((?:resolved|closed)[^)]*\))?`;
const RULE_MESSAGE = new RegExp(`^(\\S+) is ${NUMBER} \\((gte|lte|gt|lt|eq) ${NUMBER}\\) on (.+?)${ENDING}$`);
// written by evaluate_anomaly in the same file: "Anomaly detected on <machine>: <reason>". Older rows say how many readings in a row
// and the score instead.
const ANOMALY_MESSAGE = /^Anomaly detected on (.+?): /;
const OLD_ANOMALY_MESSAGE = new RegExp(`^Anomaly detected on (.+): \\d+ readings in a row outside its normal range \\(score ${NUMBER}\\)$`);

export function parseAlertMessage(message: string | null | undefined): ParsedAlertMessage | null {
  if (!message) return null;
  const text = message.trim();
  const rule = RULE_MESSAGE.exec(text);
  if (rule) {
    const value = Number(rule[2]);
    const threshold = Number(rule[4]);
    if (!Number.isFinite(value) || !Number.isFinite(threshold)) return null;
    return { metric: rule[1], value, comparison: rule[3] as Comparison, threshold, deviceName: rule[5] };
  }
  const old = OLD_ANOMALY_MESSAGE.exec(text);
  if (old) {
    const value = Number(old[2]);
    if (!Number.isFinite(value)) return null;
    return { metric: 'anomaly', value, comparison: null, threshold: null, deviceName: old[1] };
  }
  const anomaly = ANOMALY_MESSAGE.exec(text);
  // no figure in the current message: the model's figures are in the alert's own fields
  if (anomaly) return { metric: 'anomaly', value: Number.NaN, comparison: null, threshold: null, deviceName: anomaly[1] };
  return null;
}

function normalSeverity(s: string | null): Severity {
  return s === 'critical' || s === 'warning' ? s : 'info';
}

const COMPARISON_WORDS: Record<Comparison, string> = {
  gt: 'over',
  lt: 'under',
  gte: 'at or over',
  lte: 'at or under',
  eq: 'equal to',
};

export function comparisonWords(c: Comparison): string {
  return COMPARISON_WORDS[c];
}

// fewer decimals for bigger numbers: 1013 hPa, 38.7 degrees, 0.12 g
export function formatReading(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 100) return n.toFixed(0);
  if (abs >= 10) return n.toFixed(1);
  return n.toFixed(2);
}

const METRIC_LABELS: Record<string, string> = {
  vib_magnitude: 'vibration',
  fft_peak_hz: 'vibration peak',
  current_ma: 'current',
  gas_level: 'gas level',
  contact_temp: 'contact temperature',
  ir_temperature: 'IR temperature',
  moisture_level: 'moisture',
  light_level: 'light level',
  sound_level: 'sound level',
  bus_voltage: 'bus voltage',
  power_mw: 'power',
  shaft_rpm: 'shaft speed',
  distance_mm: 'distance',
  nano_temp: 'Nano air temperature',
  nano_hum: 'Nano humidity',
  nano_pres: 'Nano pressure',
  vib_rms_x: 'vibration strength X',
  vib_rms_y: 'vibration strength Y',
  vib_rms_z: 'vibration strength Z',
  vib_peak: 'largest vibration sample',
};

// a telemetry column name in plain words: "vib_magnitude" becomes "vibration"
export function metricLabel(metric: string): string {
  return Object.hasOwn(METRIC_LABELS, metric) ? METRIC_LABELS[metric] : metric.replace(/_/g, ' ');
}

// the unit each telemetry column is read in, as the latest readings table prints it (lib/readingGroups.ts holds the same
// units and a test compares the two). Written here so this file needs no import.
const METRIC_UNITS: Record<string, string> = {
  temperature: '°C',
  humidity: '%',
  pressure: 'hPa',
  vibration_x: 'g',
  vibration_y: 'g',
  vibration_z: 'g',
  gyro_x: '°/s',
  gyro_y: '°/s',
  gyro_z: '°/s',
  vib_magnitude: 'g',
  fft_peak_hz: 'Hz',
  bus_voltage: 'V',
  current_ma: 'mA',
  power_mw: 'mW',
  ir_temperature: '°C',
  contact_temp: '°C',
  distance_mm: 'mm',
  gas_level: 'counts',
  shaft_angle: '°',
  shaft_rpm: 'RPM',
  sound_level: 'counts',
  light_level: 'counts',
  moisture_level: 'counts',
  nano_temp: '°C',
  nano_hum: '%',
  nano_pres: 'hPa',
  nano_light: 'counts',
  nano_moist: 'counts',
  vib_rms_x: 'g',
  vib_rms_y: 'g',
  vib_rms_z: 'g',
  vib_peak: 'g',
  stm32_vib_x: 'g',
  stm32_vib_y: 'g',
  stm32_vib_z: 'g',
};

export function metricUnit(metric: string): string {
  // an own-property check: a metric called "constructor" has no unit
  return Object.hasOwn(METRIC_UNITS, metric) ? METRIC_UNITS[metric] : '';
}

export const METRIC_UNIT_KEYS = Object.keys(METRIC_UNITS);

// a number and its unit with a non-breaking space between them. A percent sign follows its number directly.
function withUnit(value: string, unit: string): string {
  if (!unit) return value;
  return unit === '%' ? `${value}%` : `${value}\u00a0${unit}`;
}

// "Temperature 38.7 °C over 30.0 °C". Returns null when the group has no parsed metric, so the caller shows the message.
export function describeBreach(group: { metric: string | null; latestValue: number | null; threshold: number | null; comparison: Comparison | null }): string | null {
  if (group.metric === null || group.latestValue === null || Number.isNaN(group.latestValue)) return null;
  const upper = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);
  if (group.metric === 'anomaly') return `Anomaly score ${formatReading(group.latestValue)}`;
  const unit = metricUnit(group.metric);
  const value = withUnit(formatReading(group.latestValue), unit);
  if (group.comparison === null || group.threshold === null) return upper(`${metricLabel(group.metric)} ${value}`);
  // a whole-number threshold keeps one decimal so "30" reads as "30.0" beside the reading
  const limitText = Math.abs(group.threshold) < 100 && Number.isInteger(group.threshold) ? group.threshold.toFixed(1) : formatReading(group.threshold);
  return upper(`${metricLabel(group.metric)} ${value} ${comparisonWords(group.comparison)} ${withUnit(limitText, unit)}`);
}

// counts of alerts by severity, for the stat strip
export function countBySeverity(alerts: readonly Pick<AlertInput, 'severity'>[]): Record<Severity, number> {
  const out: Record<Severity, number> = { critical: 0, warning: 0, info: 0 };
  for (const a of alerts) out[normalSeverity(a.severity)] += 1;
  return out;
}
