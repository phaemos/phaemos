// kept so the imports written before lib/format.ts existed still work. New code imports from lib/format.
// the import has no file extension on purpose: the app resolves it. This file is not loaded by the Node tests.
import { formatDateTimeExact, formatRelative, type TimeInput } from './format';

export function relativeTime(iso: TimeInput, now: number = Date.now()): string {
  return formatRelative(iso, now);
}

export function absoluteTime(iso: TimeInput): string {
  return formatDateTimeExact(iso);
}
