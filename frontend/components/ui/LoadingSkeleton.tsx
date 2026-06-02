'use client';

// I vary the widths so the skeleton does not look like a uniform loading bar,
// which feels more like real content being loaded rather than a generic spinner.

interface Props {
  rows?: number;
  className?: string;
}

// I predefine the width cycle so each row reliably gets a distinct width
// without needing random numbers that would break server/client hydration.
const ROW_WIDTHS = ['w-full', 'w-5/6', 'w-4/5'];

export default function LoadingSkeleton({ rows = 3, className = '' }: Props) {
  return (
    <div className={`space-y-3 ${className}`} aria-label="Loading...">
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className={`h-4 rounded bg-gray-200 dark:bg-gray-700 animate-pulse ${ROW_WIDTHS[i % ROW_WIDTHS.length]}`}
        />
      ))}
    </div>
  );
}
