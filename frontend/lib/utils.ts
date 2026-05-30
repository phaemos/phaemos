// I keep all pure formatting helpers in one place so components stay thin
// and the same formatting logic is never duplicated across the codebase.

/**
 * formatDate
 * I format ISO strings to "DD MMM YYYY HH:mm" because the dashboard
 * operators are used to reading day-first dates and the 24-hour clock
 * avoids AM/PM ambiguity during night shifts.
 */
export function formatDate(iso: string): string {
  const d = new Date(iso);
  const day = String(d.getDate()).padStart(2, '0');
  const month = d.toLocaleString('en-GB', { month: 'short' });
  const year = d.getFullYear();
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${day} ${month} ${year} ${hh}:${mm}`;
}

/**
 * formatSensorValue
 * I return "-- unit" when value is null so every sensor field always renders
 * a string - components never need to guard against undefined display values.
 */
export function formatSensorValue(
  value: number | null,
  unit: string,
  decimals: number = 1,
): string {
  if (value === null || value === undefined) {
    return `-- ${unit}`;
  }
  return `${value.toFixed(decimals)} ${unit}`;
}

/**
 * severityColor
 * I return a Tailwind text-color class rather than a raw hex so the palette
 * stays consistent with the rest of the UI and respects Tailwind's purge list.
 */
export function severityColor(
  severity: 'info' | 'warning' | 'critical',
): string {
  switch (severity) {
    case 'info':
      return 'text-blue-400';
    case 'warning':
      return 'text-amber-400';
    case 'critical':
      return 'text-red-400';
    default:
      return 'text-gray-400';
  }
}

/**
 * clamp
 * I provide clamp as a named utility rather than inlining Math.min/Math.max
 * so the intent is obvious at every call site.
 */
export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

/**
 * nodeTypeLabel
 * I map the raw node_type string from firmware to a human-readable label
 * so operators see descriptive board names rather than internal identifiers.
 */
export function nodeTypeLabel(nodeType: string | null): string {
  if (!nodeType) return 'Unknown';
  switch (nodeType.toLowerCase()) {
    case 'esp32':
    case 'esp32_primary':
      return 'ESP32 Primary';
    case 'stm32':
    case 'stm32_vibration':
      return 'STM32 Vibration';
    case 'arduino':
    case 'arduino_nano':
      return 'Arduino Nano';
    case 'pico':
    case 'pico_2w':
    case 'pico_2w_ambient':
      return 'Pico 2W Ambient';
    default:
      return 'Unknown';
  }
}
