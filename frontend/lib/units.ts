// a number and its unit are always written with a non-breaking space between them, so "23.4 °C" never splits over
// two lines. A percent sign follows its number directly, as in UK usage. One place decides, so every reading reads the same.

export const NBSP = ' ';

// 23.4 °C, 1013.2 hPa, 45%. A missing value reads as a dash with the unit left off.
export function formatReading(value: number | null | undefined, unit: string, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  const n = value.toFixed(digits);
  if (!unit) return n;
  return unit === '%' ? `${n}%` : `${n}${NBSP}${unit}`;
}

// joins any number and unit that were written with an ordinary space, for text from the API or a constant
export function tieUnit(text: string): string {
  return text.replace(/(\d)\s+(°C|°F|g|Hz|hPa|mA|mV|V|mm|ms|s|min|h|d|MB|KB|GB)\b/g, `$1${NBSP}$2`);
}
