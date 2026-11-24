// the readings an alert rule can watch: the numeric fields of a telemetry reading (types/index.ts, Telemetry);
// the API matches the key against the reading, so a typo makes a rule that never fires. Offering a list avoids that.

export const ALERT_METRICS = [
  { key: 'temperature', label: 'Air temperature' },
  { key: 'humidity', label: 'Humidity' },
  { key: 'pressure', label: 'Pressure' },
  { key: 'vibration_x', label: 'Vibration, x axis' },
  { key: 'vibration_y', label: 'Vibration, y axis' },
  { key: 'vibration_z', label: 'Vibration, z axis' },
  { key: 'vib_magnitude', label: 'Vibration magnitude' },
  { key: 'fft_peak_hz', label: 'Vibration peak frequency' },
  { key: 'gyro_x', label: 'Rotation, x axis' },
  { key: 'gyro_y', label: 'Rotation, y axis' },
  { key: 'gyro_z', label: 'Rotation, z axis' },
  { key: 'bus_voltage', label: 'Bus voltage' },
  { key: 'current_ma', label: 'Current' },
  { key: 'power_mw', label: 'Power' },
  { key: 'ir_temperature', label: 'Surface temperature' },
  { key: 'contact_temp', label: 'Contact temperature' },
  { key: 'distance_mm', label: 'Distance' },
  { key: 'gas_level', label: 'Gas level' },
  { key: 'shaft_angle', label: 'Shaft angle' },
  { key: 'shaft_rpm', label: 'Shaft speed' },
  { key: 'sound_level', label: 'Sound level' },
  { key: 'light_level', label: 'Light level' },
  { key: 'moisture_level', label: 'Moisture level' },
  { key: 'anomaly_score', label: 'Anomaly score' },
] as const;

// a rule made before this list existed may name a key that is not in it, so it shows as the raw key
export function metricLabel(key: string): string {
  return ALERT_METRICS.find((m) => m.key === key)?.label ?? key;
}

export const CONDITION_WORDS: Record<string, string> = { gt: 'Above', lt: 'Below', eq: 'Equal to' };
