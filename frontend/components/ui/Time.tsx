import { cn } from '@/lib/cn';
import { serverNow } from '@/lib/serverClock';
import { formatDate, formatDateTime, formatDateTimeExact, formatRelative, type TimeInput } from '@/lib/format';

interface Props {
  value: TimeInput;
  // date: 22 Nov 2026. datetime: 22 Nov 2026, 00:10. exact: with seconds. relative: 5 min ago, with the exact time in a title
  format?: 'date' | 'datetime' | 'exact' | 'relative';
  // a fixed clock for relative times, so a sample renders the same text every time
  now?: number;
  // shown when there is no usable value
  fallback?: string;
  className?: string;
  // relative only: write the exact time after it in brackets, for a place where the exact time matters (a detail panel)
  showExact?: boolean;
}

// the one way a date or time reaches the screen. One form everywhere: "22 Nov 2026, 00:10" for a moment, "22 Nov 2026" for a
// day and a relative "5 min ago" for something recent. A relative time always carries its exact time as text for assistive
// technology and visibly too with showExact, because a title is out of reach of a keyboard or a touch screen. Seconds
// appear only in the title. a `time` element with a machine-readable dateTime, set in the sans
// face with tabular figures so columns of times line up without the wide gaps of the mono face. Mono is for readings
// with units, versions, ids and code.
export default function Time({ value, format = 'datetime', now, fallback = '', className, showExact = false }: Props) {
  const d = value === null || value === undefined || value === '' ? null : new Date(value);
  if (!d || Number.isNaN(d.getTime())) {
    // a relative time still says "never" or "unknown" for a missing value
    return format === 'relative' ? <span className={className}>{formatRelative(value, now ?? serverNow())}</span> : <>{fallback}</>;
  }
  const text = format === 'date' ? formatDate(value) : format === 'exact' ? formatDateTimeExact(value) : format === 'relative' ? formatRelative(value, now ?? serverNow()) : formatDateTime(value);
  return (
    <time dateTime={d.toISOString()} title={format === 'relative' || format === 'datetime' ? formatDateTimeExact(value) : undefined} className={cn('tnum', className)}>
      {text}
      {format === 'relative' && (showExact ? <span className="ml-1.5 text-meta text-surface-700 dark:text-surface-300">({formatDateTime(value)})</span> : <span className="sr-only">, {formatDateTime(value)}</span>)}
    </time>
  );
}
