'use client';

import { useId, useRef, type KeyboardEvent } from 'react';
import { cn } from '@/lib/cn';

// one control for choosing a single option. A quiet track with a hairline holds the options. The chosen one has a
// raised background and bolder text, so it is not marked by colour alone. Radio group semantics: Tab enters the
// chosen option and the arrow keys move and choose. When the options do not fit, the track scrolls sideways
// inside itself and never wraps.

interface Option<T extends string> {
  value: T;
  label: string;
}

interface Props<T extends string> {
  options: readonly Option<T>[];
  value: T;
  onChange: (value: T) => void;
  // names the control. It is shown above the track in the same style Field gives a label, so every control in a
  // filter row reads alike. hideLabel keeps it for screen readers only.
  label: string;
  hideLabel?: boolean;
  className?: string;
}

export default function Segmented<T extends string>({ options, value, onChange, label, hideLabel = false, className }: Props<T>) {
  const labelId = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next = index;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (index + 1) % options.length;
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = (index - 1 + options.length) % options.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = options.length - 1;
    else return;
    e.preventDefault();
    refs.current[next]?.focus();
    onChange(options[next].value);
  }

  return (
    <div className={cn('min-w-0 max-w-full space-y-1.5', className)}>
      <span id={labelId} className={hideLabel ? 'sr-only' : 'block text-base font-medium text-surface-900 dark:text-surface-50'}>{label}</span>
      <div
        role="radiogroup"
        aria-labelledby={labelId}
        className="flex max-w-full overflow-x-auto rounded-md border border-surface-500 bg-surface-0 dark:bg-surface-900 sm:inline-flex"
      >
        {options.map((o, i) => {
          const active = o.value === value;
          return (
            <button
              key={o.value}
              ref={(el) => { refs.current[i] = el; }}
              type="button"
              role="radio"
              aria-checked={active}
              tabIndex={active ? 0 : -1}
              onClick={() => onChange(o.value)}
              onKeyDown={(e) => onKeyDown(e, i)}
              // 42 px inside a 1 px border makes the track 44 px high, level with every input and select beside it
              data-hit=""
              className={cn(
                // the pseudo-element reaches over the track's 1 px border, so the whole 44 px height answers a press
                'relative inline-flex h-[42px] min-w-[44px] shrink-0 items-center justify-center rounded-[5px] px-3 text-base whitespace-nowrap transition-colors duration-150 ease-out before:absolute before:-inset-px before:content-[\'\']',
                active
                  ? 'bg-surface-100 font-semibold text-surface-900 ring-2 ring-inset ring-surface-500 dark:bg-surface-700 dark:text-surface-50 dark:ring-surface-400'
                  : 'font-medium text-surface-700 hover:bg-surface-100 hover:text-surface-900 dark:text-surface-300 dark:hover:bg-surface-800 dark:hover:text-surface-50',
              )}
            >
              {o.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
