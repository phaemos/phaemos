'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { cn } from '@/lib/cn';

interface Props {
  caption: string;
  children: ReactNode;
  maxHeightClass?: string;
  className?: string;
  // a hairline border and rounded corners around the table, for a table that sits on the page and not in a panel
  framed?: boolean;
  // the width below which the table stops shrinking and the wrapper scrolls, as a CSS length such as "44rem"
  minWidth?: string;
}

// a table inside a wrapper that scrolls when the table is wider or taller than its box. A wrapper that scrolls must be
// reachable by keyboard, so it becomes a labelled, focusable region exactly while it overflows (a wrapper that never
// scrolls adds no tab stop).
export default function DataTable({ caption, children, maxHeightClass, className, framed, minWidth }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [scrolls, setScrolls] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () => setScrolls(el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1);
    check();
    const observer = new ResizeObserver(check);
    observer.observe(el);
    const table = el.firstElementChild;
    if (table) observer.observe(table);
    return () => observer.disconnect();
  }, []);

  // a wrapper given a real height limit scrolls by design. max-h-none is the way to say "never limit the height", so it earns a
  // tab stop only while the table is wider than its box.
  const focusable = (Boolean(maxHeightClass) && maxHeightClass !== 'max-h-none') || scrolls;
  // relative makes the wrapper the containing block of any visually hidden text inside a cell, so that text is clipped with the
  // table and cannot widen the page when the table scrolls sideways
  return (
    <div ref={ref} className={cn('relative overflow-auto', framed && 'rounded-lg border border-surface-200 dark:border-surface-800', maxHeightClass, className)} tabIndex={focusable ? 0 : undefined} role={focusable ? 'region' : undefined} aria-label={focusable ? caption : undefined}>
      <table className="data-table" style={minWidth ? { minWidth } : undefined}>
        <caption className="sr-only">{caption}</caption>
        {children}
      </table>
    </div>
  );
}
