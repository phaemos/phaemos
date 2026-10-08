'use client';

// one bordered control for picking a single option, used in place of a row of separate pill
// buttons so filters read as one decision rather than many

interface Option<T extends string> {
  value: T;
  label: string;
}

interface Props<T extends string> {
  options: readonly Option<T>[];
  value: T;
  onChange: (value: T) => void;
  label: string;
  size?: 'sm' | 'md';
}

export default function Segmented<T extends string>({ options, value, onChange, label, size = 'sm' }: Props<T>) {
  const pad = size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3 py-1.5 text-sm';
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-lg border border-surface-200 dark:border-surface-800 bg-surface-100/60 dark:bg-surface-900 p-0.5">
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(o.value)}
            className={`${pad} rounded-md font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-brand-500 ${
              active
                ? 'bg-white dark:bg-surface-700 text-surface-900 dark:text-white shadow-sm'
                : 'text-surface-500 dark:text-surface-400 hover:text-surface-900 dark:hover:text-surface-100'
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
