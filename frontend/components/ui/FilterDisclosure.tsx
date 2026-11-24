'use client';

import { useId, useState, type ReactNode } from 'react';
import { ChevronIcon, ChevronUpIcon } from './icons';

interface Props {
  // how many filters differ from their defaults. The button says so and the group starts open only when it is above zero.
  count: number;
  children: ReactNode;
  className?: string;
}

// below 768 px the filters sit behind one "Filters" button so a phone shows the list and not a screen of controls. From 768
// px the controls are always shown and the button is not. The button reports its state and how many filters are active.
export default function FilterDisclosure({ count, children, className = '' }: Props) {
  const [open, setOpen] = useState(count > 0);
  const id = useId();
  return (
    <div className={className}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex min-h-[44px] items-center gap-2 rounded-md border border-surface-500 bg-surface-0 px-4 text-base font-medium text-surface-900 hover:bg-surface-100 dark:bg-surface-900 dark:text-surface-50 dark:hover:bg-surface-800 md:hidden"
      >
        Filters
        <span className="tnum font-normal text-surface-700 dark:text-surface-300">{count === 0 ? 'none active' : `${count} active`}</span>
        {open ? <ChevronUpIcon size={16} /> : <ChevronIcon size={16} />}
      </button>
      <div id={id} className={`${open ? 'mt-3 block' : 'hidden'} md:mt-0 md:block`}>
        {children}
      </div>
    </div>
  );
}
