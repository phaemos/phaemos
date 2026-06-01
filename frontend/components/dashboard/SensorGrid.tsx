'use client';

// I group sensors by category rather than listing all fields flat because the
// dashboard operator needs to quickly locate the relevant group during an alert
// - scanning a grouped card layout is much faster than reading a single long list.

import type { Telemetry } from '../../types/index';
import { formatSensorValue } from '../../lib/utils';
import LoadingSkeleton from '../ui/LoadingSkeleton';

interface Props {
  reading: Telemetry | null;
}

interface SensorField {
  label: string;
  value: string;
  alert?: boolean;
}

interface SensorCategory {
  title: string;
  fields: SensorField[];
}

// I build the category list inside the component rather than at module level
// so it is recalculated on every render and always reflects the latest reading.
function buildCategories(r: Telemetry): SensorCategory[] {
  return [
    {
      title: 'Environment (BME280)',
      fields: [
        { label: 'Temperature', value: formatSensorValue(r.temperature, 'degC') },
        { label: 'Humidity', value: formatSensorValue(r.humidity, '%') },
        { label: 'Pressure', value: formatSensorValue(r.pressure, 'hPa') },
      ],
    },
    {
      title: 'Motion (MPU6050)',
      fields: [
        { label: 'Vibration X', value: formatSensorValue(r.vibration_x, 'g', 3) },
        { label: 'Vibration Y', value: formatSensorValue(r.vibration_y, 'g', 3) },
        { label: 'Vibration Z', value: formatSensorValue(r.vibration_z, 'g', 3) },
        { label: 'Gyro X', value: formatSensorValue(r.gyro_x, 'deg/s', 2) },
        { label: 'Gyro Y', value: formatSensorValue(r.gyro_y, 'deg/s', 2) },
        { label: 'Gyro Z', value: formatSensorValue(r.gyro_z, 'deg/s', 2) },
      ],
    },
    {
      title: 'Power (INA219)',
      fields: [
        { label: 'Bus Voltage', value: formatSensorValue(r.bus_voltage, 'V', 2) },
        { label: 'Current', value: formatSensorValue(r.current_ma, 'mA', 1) },
        { label: 'Power', value: formatSensorValue(r.power_mw, 'mW', 1) },
      ],
    },
    {
      title: 'Thermal',
      fields: [
        {
          label: 'IR Temp (MLX90614)',
          value: formatSensorValue(r.ir_temperature, 'degC'),
        },
        {
          label: 'Contact Temp (DS18B20)',
          value: formatSensorValue(r.contact_temp, 'degC'),
        },
      ],
    },
    {
      title: 'Proximity',
      fields: [
        { label: 'Distance', value: formatSensorValue(r.distance_mm, 'mm', 0) },
      ],
    },
    {
      title: 'Gas (MQ-2)',
      fields: [
        { label: 'Gas Level', value: formatSensorValue(r.gas_level, 'raw', 0) },
        // I use a sentinel alert field for gas_alert so the card can render a
        // red badge inline rather than a plain text value.
        {
          label: 'Gas Alert',
          value: r.gas_alert ? 'ALERT' : 'Clear',
          alert: r.gas_alert === true,
        },
      ],
    },
    {
      title: 'Rotation (AS5600)',
      fields: [
        { label: 'Shaft Angle', value: formatSensorValue(r.shaft_angle, 'deg', 1) },
        { label: 'Shaft RPM', value: formatSensorValue(r.shaft_rpm, 'RPM', 0) },
      ],
    },
    {
      title: 'Sound (MAX4466)',
      fields: [
        { label: 'Sound Level', value: formatSensorValue(r.sound_level, 'raw', 0) },
      ],
    },
    {
      title: 'Light (LDR)',
      fields: [
        { label: 'Light Level', value: formatSensorValue(r.light_level, 'raw', 0) },
      ],
    },
    {
      title: 'Moisture (FC-28)',
      fields: [
        {
          label: 'Moisture Level',
          value: formatSensorValue(r.moisture_level, 'raw', 0),
        },
        {
          label: 'Water Detected',
          value: r.water_detected ? 'DETECTED' : 'Clear',
          alert: r.water_detected === true,
        },
      ],
    },
    {
      title: 'Vibration FFT (STM32)',
      fields: [
        {
          label: 'FFT Peak',
          value: formatSensorValue(r.fft_peak_hz, 'Hz', 1),
        },
        {
          label: 'Vib Magnitude',
          value: formatSensorValue(r.vib_magnitude, 'g', 3),
        },
      ],
    },
  ];
}

export default function SensorGrid({ reading }: Props) {
  if (!reading) {
    // I show the skeleton at grid layout so the placeholder occupies the same
    // visual space as the real grid, preventing layout shift on load.
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {Array.from({ length: 11 }).map((_, i) => (
          <div key={i} className="bg-gray-50 dark:bg-white/5 rounded-xl p-4 border border-gray-200 dark:border-gray-700">
            <LoadingSkeleton rows={3} />
          </div>
        ))}
      </div>
    );
  }

  const categories = buildCategories(reading);

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {categories.map((cat) => (
        <div
          key={cat.title}
          className="bg-gray-50 dark:bg-white/5 rounded-xl p-4 border border-gray-200 dark:border-gray-700"
        >
          <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
            {cat.title}
          </h3>
          <dl className="space-y-1.5">
            {cat.fields.map((field) => (
              <div key={field.label} className="flex justify-between items-center">
                <dt className="text-xs text-gray-400 dark:text-gray-500">{field.label}</dt>
                <dd>
                  {field.alert ? (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-red-900/60 text-red-300 border border-red-700">
                      <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
                      {field.value}
                    </span>
                  ) : (
                    <span className="text-xs font-mono text-gray-800 dark:text-gray-200">
                      {field.value}
                    </span>
                  )}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
    </div>
  );
}
