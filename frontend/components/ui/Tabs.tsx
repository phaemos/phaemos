'use client';

import Link from 'next/link';
import { useRef, type KeyboardEvent, type ReactNode } from 'react';
import { cn } from '@/lib/cn';

export interface TabItem<T extends string> {
  value: T;
  label: string;
  count?: number;
  // set on every item to render links instead of buttons: the view then works without script
  href?: string;
}

interface Props<T extends string> {
  items: readonly TabItem<T>[];
  value: T;
  label: string;
  onChange?: (value: T) => void;
  // button mode: tabs get ids and aria-controls built from this prefix so a panel can point back at them
  idPrefix?: string;
  className?: string;
  children?: ReactNode;
}

const TAB =
  'relative inline-flex min-h-[44px] items-center gap-2 px-3 text-base font-medium whitespace-nowrap transition-colors duration-150 ease-out';

// one underlined tab row. Buttons use roving focus (one tab stop, arrow keys move) and links keep every
// link in the tab order so they work without script, with the arrow keys as an extra.
export default function Tabs<T extends string>({ items, value, label, onChange, idPrefix = 'tabs', className }: Props<T>) {
  const refs = useRef<(HTMLElement | null)[]>([]);
  const linkMode = items.every((i) => i.href !== undefined);

  function onKeyDown(e: KeyboardEvent<HTMLElement>, index: number) {
    let next = index;
    if (e.key === 'ArrowRight') next = (index + 1) % items.length;
    else if (e.key === 'ArrowLeft') next = (index - 1 + items.length) % items.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = items.length - 1;
    else return;
    e.preventDefault();
    refs.current[next]?.focus();
    // buttons select as focus moves, as the tabs pattern expects. Links wait for Enter.
    if (!linkMode) onChange?.(items[next].value);
  }

  const inner = (item: TabItem<T>) => (
    <>
      {item.label}
      {item.count !== undefined && (
        <span className="tnum rounded-full bg-surface-100 px-1.5 text-meta text-surface-700 dark:bg-surface-800 dark:text-surface-300">{item.count}</span>
      )}
    </>
  );

  const state = (active: boolean) =>
    cn(
      TAB,
      active
        ? 'text-surface-900 after:absolute after:inset-x-2 after:bottom-0 after:h-0.5 after:bg-brand-600 dark:text-surface-50 dark:after:bg-brand-400'
        : 'text-surface-600 hover:text-surface-900 dark:text-surface-400 dark:hover:text-surface-50',
    );

  if (linkMode) {
    return (
      <nav aria-label={label} className={cn('border-b border-surface-200 dark:border-surface-800', className)}>
        <ul className="-mb-px flex gap-1 overflow-x-auto">
          {items.map((item, i) => (
            <li key={item.value}>
              <Link
                href={item.href as string}
                ref={(el) => { refs.current[i] = el; }}
                aria-current={item.value === value ? 'page' : undefined}
                onKeyDown={(e) => onKeyDown(e, i)}
                className={state(item.value === value)}
              >
                {inner(item)}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    );
  }

  return (
    <div role="tablist" aria-label={label} className={cn('-mb-px flex gap-1 overflow-x-auto border-b border-surface-200 dark:border-surface-800', className)}>
      {items.map((item, i) => {
        const active = item.value === value;
        return (
          <button
            key={item.value}
            type="button"
            role="tab"
            id={`${idPrefix}-tab-${item.value}`}
            aria-selected={active}
            aria-controls={`${idPrefix}-panel-${item.value}`}
            tabIndex={active ? 0 : -1}
            ref={(el) => { refs.current[i] = el; }}
            onClick={() => onChange?.(item.value)}
            onKeyDown={(e) => onKeyDown(e, i)}
            className={state(active)}
          >
            {inner(item)}
          </button>
        );
      })}
    </div>
  );
}
