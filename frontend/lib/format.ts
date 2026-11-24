// the one place dates and times become text. Every format is UK English and day first, so the same moment never
// reads two ways on two pages. `now` is a parameter wherever it matters so a fixed sample renders the same text.

export type TimeInput = string | number | Date | null | undefined;

function toDate(value: TimeInput): Date | null {
  if (value === null || value === undefined || value === '') return null;
  const d = value instanceof Date ? value : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

// "22 Nov 2026". An empty string when there is no usable value, so a caller can fall back to its own words.
export function formatDate(value: TimeInput): string {
  const d = toDate(value);
  if (!d) return '';
  // a date with no time ("2026-11-22") means midnight UTC, which is the day before in a zone west of Greenwich, so it is
  // read in UTC. A full timestamp is shown in the reader's own zone.
  const dateOnly = typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value);
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', ...(dateOnly ? { timeZone: 'UTC' } : {}) });
}

// "22 Nov 2026, 00:10" on the 24-hour clock, which avoids am and pm doubt on night shifts.
export function formatDateTime(value: TimeInput): string {
  const d = toDate(value);
  if (!d) return '';
  return d.toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
}

// "22 Nov 2026, 00:10:05": the exact moment, for a title attribute beside a relative label.
export function formatDateTimeExact(value: TimeInput): string {
  const d = toDate(value);
  if (!d) return '';
  return d.toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}

// "just now", "5 min ago", "3 h ago", "2 d ago". A missing value reads "never" and an unreadable one "unknown".
export function formatRelative(value: TimeInput, now: number = Date.now()): string {
  if (value === null || value === undefined || value === '') return 'never';
  const d = toDate(value);
  if (!d) return 'unknown';
  const secs = Math.max(0, Math.round((now - d.getTime()) / 1000));
  if (secs < 60) return 'just now';
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

// "admin" as "Admin": a role is a name and is written with a capital wherever a person reads it
export function roleWord(role: string | null | undefined): string {
  return role ? role.charAt(0).toUpperCase() + role.slice(1) : '';
}

// "1 reading", "2 readings": the count with the right form of the word. One helper so no page prints "1 readings".
export function plural(count: number, one: string, many: string = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}

// a number tied to its unit with a non-breaking space, "5 min" and a percent sign joined directly, "48%"
export function withUnit(value: string | number, unit: string): string {
  if (!unit) return String(value);
  return unit === '%' ? `${value}%` : `${value}\u00a0${unit}`;
}

// a counter for a person: digits in groups of three and, from a million, the size in words. A counter that has run away (a node
// that restarted its numbering) reads "1,795,312,815 (about 1.8 billion)" and not a bare run of digits.
export function formatCount(n: number): string {
  if (!Number.isFinite(n)) return '';
  const grouped = Math.round(n).toLocaleString('en-GB');
  if (n >= 1e9) return `${grouped} (about ${(n / 1e9).toFixed(1)} billion)`;
  if (n >= 1e6) return `${grouped} (about ${(n / 1e6).toFixed(1)} million)`;
  return grouped;
}
