// the latest readings of one machine, grouped by the sensor that took them. A node only posts the fields it
// carries, so each reading holds nulls for the rest. A group is shown when a recent reading holds a value for it
// or when the machine's node type carries that sensor (docs/sensor_reference.md). The second case is how a quiet
// sensor shows as "no reading" instead of vanishing.

export interface FieldSpec {
  key: string;
  label: string;
  unit: string;
  digits: number;
  kind?: 'number' | 'flag';
  // flags only: the words for true and false
  trueWord?: string;
  falseWord?: string;
  // flags only: the numeric field of the same sensor. A flag the sensor never sent is stored as false, so "clear" is only true
  // when the sensor's own level is a number in the same row. Otherwise there is no reading.
  requires?: string;
}

export interface SensorSpec {
  id: string;
  // what a person calls it
  name: string;
  // the part, kept as a quiet second line
  model: string;
  // node types that carry this sensor, from docs/sensor_reference.md
  carriedBy: readonly string[];
  fields: readonly FieldSpec[];
}

export const SENSORS: readonly SensorSpec[] = [
  {
    id: 'air', name: 'Air', model: 'BME280', carriedBy: ['esp32', 'nano', 'pico_w'],
    fields: [
      { key: 'temperature', label: 'Temperature', unit: '°C', digits: 1 },
      { key: 'humidity', label: 'Humidity', unit: '%', digits: 1 },
      { key: 'pressure', label: 'Pressure', unit: 'hPa', digits: 1 },
    ],
  },
  {
    id: 'motion', name: 'Motion', model: 'MPU6050', carriedBy: ['esp32', 'stm32'],
    fields: [
      { key: 'vibration_x', label: 'Acceleration X', unit: 'g', digits: 3 },
      { key: 'vibration_y', label: 'Acceleration Y', unit: 'g', digits: 3 },
      { key: 'vibration_z', label: 'Acceleration Z', unit: 'g', digits: 3 },
      { key: 'gyro_x', label: 'Rotation rate X', unit: '°/s', digits: 2 },
      { key: 'gyro_y', label: 'Rotation rate Y', unit: '°/s', digits: 2 },
      { key: 'gyro_z', label: 'Rotation rate Z', unit: '°/s', digits: 2 },
    ],
  },
  {
    id: 'vibration', name: 'Vibration analysis', model: 'STM32 FFT', carriedBy: ['esp32', 'stm32'],
    fields: [
      { key: 'vib_magnitude', label: 'Vibration magnitude', unit: 'g', digits: 3 },
      { key: 'fft_peak_hz', label: 'Vibration peak', unit: 'Hz', digits: 1 },
    ],
  },
  {
    id: 'power', name: 'Power', model: 'INA219', carriedBy: ['esp32'],
    fields: [
      { key: 'bus_voltage', label: 'Bus voltage', unit: 'V', digits: 2 },
      { key: 'current_ma', label: 'Current', unit: 'mA', digits: 1 },
      { key: 'power_mw', label: 'Power', unit: 'mW', digits: 1 },
    ],
  },
  {
    id: 'infrared', name: 'Surface temperature', model: 'MLX90614', carriedBy: ['esp32'],
    fields: [{ key: 'ir_temperature', label: 'Infrared temperature', unit: '°C', digits: 1 }],
  },
  {
    id: 'contact', name: 'Contact temperature', model: 'DS18B20', carriedBy: ['esp32'],
    fields: [{ key: 'contact_temp', label: 'Contact temperature', unit: '°C', digits: 1 }],
  },
  {
    id: 'distance', name: 'Distance', model: 'VL53L0X', carriedBy: ['esp32'],
    fields: [{ key: 'distance_mm', label: 'Distance', unit: 'mm', digits: 0 }],
  },
  {
    id: 'gas', name: 'Gas', model: 'MQ-2', carriedBy: ['esp32'],
    fields: [
      { key: 'gas_level', label: 'Gas level', unit: 'counts', digits: 0 },
      { key: 'gas_alert', label: 'Gas alarm', unit: '', digits: 0, kind: 'flag', trueWord: 'Alarm', falseWord: 'Clear', requires: 'gas_level' },
    ],
  },
  {
    id: 'shaft', name: 'Shaft', model: 'AS5600', carriedBy: ['esp32'],
    fields: [
      { key: 'shaft_angle', label: 'Shaft angle', unit: '°', digits: 1 },
      { key: 'shaft_rpm', label: 'Shaft speed', unit: 'RPM', digits: 0 },
    ],
  },
  {
    id: 'sound', name: 'Sound', model: 'MAX4466', carriedBy: ['esp32'],
    fields: [{ key: 'sound_level', label: 'Sound level', unit: 'counts', digits: 0 }],
  },
  {
    id: 'light', name: 'Light', model: 'LDR', carriedBy: ['esp32', 'nano', 'pico_w'],
    fields: [{ key: 'light_level', label: 'Light level', unit: 'counts', digits: 0 }],
  },
  {
    id: 'moisture', name: 'Moisture', model: 'FC-28', carriedBy: ['esp32', 'nano'],
    fields: [
      { key: 'moisture_level', label: 'Moisture level', unit: 'counts', digits: 0 },
      { key: 'water_detected', label: 'Water', unit: '', digits: 0, kind: 'flag', trueWord: 'Detected', falseWord: 'None', requires: 'moisture_level' },
    ],
  },
];

// the satellites' values arrive through the ESP32 hub. A group of them shows only when a reading holds a value or when a
// fault names it, so a hub with no satellite is not given rows of "no reading" for sensors it never had.
export const SATELLITE_SENSORS: readonly SensorSpec[] = [
  {
    id: 'nano_air', name: 'Air on the Nano node', model: 'BME280', carriedBy: [],
    fields: [
      { key: 'nano_temp', label: 'Temperature', unit: '°C', digits: 1 },
      { key: 'nano_hum', label: 'Humidity', unit: '%', digits: 1 },
      { key: 'nano_pres', label: 'Pressure', unit: 'hPa', digits: 1 },
    ],
  },
  {
    id: 'nano_inputs', name: 'Light and moisture on the Nano node', model: 'LDR and FC-28', carriedBy: [],
    fields: [
      { key: 'nano_light', label: 'Light level (raw count)', unit: 'counts', digits: 0 },
      { key: 'nano_moist', label: 'Moisture level (raw count)', unit: 'counts', digits: 0 },
      { key: 'nano_water', label: 'Water', unit: '', digits: 0, kind: 'flag', trueWord: 'Detected', falseWord: 'None', requires: 'nano_moist' },
    ],
  },
  {
    id: 'vib_strength', name: 'Vibration strength', model: 'STM32 MPU6050', carriedBy: [],
    fields: [
      { key: 'vib_rms_x', label: 'Strength X (RMS)', unit: 'g', digits: 3 },
      { key: 'vib_rms_y', label: 'Strength Y (RMS)', unit: 'g', digits: 3 },
      { key: 'vib_rms_z', label: 'Strength Z (RMS)', unit: 'g', digits: 3 },
      { key: 'vib_peak', label: 'Largest sample', unit: 'g', digits: 3 },
      { key: 'stm32_vib_x', label: 'Average acceleration X', unit: 'g', digits: 3 },
      { key: 'stm32_vib_y', label: 'Average acceleration Y', unit: 'g', digits: 3 },
      { key: 'stm32_vib_z', label: 'Average acceleration Z', unit: 'g', digits: 3 },
      { key: 'vib_clipping', label: 'Beyond the sensor\'s range', unit: '', digits: 0, kind: 'flag', trueWord: 'Yes, readings are cut off', falseWord: 'No', requires: 'vib_rms_x' },
    ],
  },
];

export interface ReadingRow {
  key: string;
  label: string;
  unit: string;
  digits: number;
  kind: 'number' | 'flag';
  trueWord?: string;
  falseWord?: string;
  // null when no recent reading holds this field
  value: number | boolean | null;
  // when the value was recorded
  at: string | null;
}

export interface ReadingGroup {
  id: string;
  name: string;
  model: string;
  rows: ReadingRow[];
}

// readings are newest first, as the API returns them. The newest non-null value per field wins, because each node
// type sends only its own fields and the newest reading may not hold the field a hub forwarded a moment earlier.
export function groupReadings(
  readings: readonly { recorded_at: string }[],
  nodeType: string | null | undefined,
  // true for a field a fault or a not fitted mark names, which makes its group show even with no value
  named: (field: string) => boolean = () => false,
): ReadingGroup[] {
  const groups: ReadingGroup[] = [];
  for (const s of [...SENSORS, ...SATELLITE_SENSORS]) {
    const rows: ReadingRow[] = s.fields.map((f) => {
      const kind = f.kind ?? 'number';
      for (const r of readings) {
        const v = (r as unknown as Record<string, unknown>)[f.key];
        if (kind === 'number' && typeof v === 'number') return { ...f, kind, value: v, at: r.recorded_at };
        // a raised flag is always shown as raised, whatever else is or is not in the row: an alarm must never read as clear or as no
        // reading. A false flag counts only beside a number from its own sensor, because the API stores an unsent flag as false.
        const beside = v === true || f.requires === undefined || typeof (r as unknown as Record<string, unknown>)[f.requires] === 'number';
        if (kind === 'flag' && typeof v === 'boolean' && beside) return { ...f, kind, value: v, at: r.recorded_at };
      }
      return { ...f, kind, value: null, at: null };
    });
    const carried = !!nodeType && s.carriedBy.includes(nodeType);
    if (carried || rows.some((r) => r.value !== null || named(r.key))) groups.push({ id: s.id, name: s.name, model: s.model, rows });
  }
  return groups;
}

// the value as text with its unit. A flag reads as a word. The caller marks a missing value, which has no text;
// a raised flag is also a state, so the caller shows it with a shape (isRaised)
export function formatReadingValue(row: ReadingRow): string | null {
  if (row.value === null) return null;
  if (row.kind === 'flag') return row.value ? (row.trueWord ?? 'Yes') : (row.falseWord ?? 'No');
  const n = Number(row.value);
  // a non-breaking space ties the number to its unit so they never split over two lines. A percent sign follows directly.
  if (!row.unit) return n.toFixed(row.digits);
  return row.unit === '%' ? `${n.toFixed(row.digits)}%` : `${n.toFixed(row.digits)}\u00a0${row.unit}`;
}

// true for a flag that is on, so the page can add a shape to the word
export function isRaised(row: ReadingRow): boolean {
  return row.kind === 'flag' && row.value === true;
}
