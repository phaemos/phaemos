import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

// running text at body size in a column that stops at 72 characters
export default function Prose({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn('max-w-[72ch] space-y-4 text-base text-surface-700 dark:text-surface-300', className)}>
      {children}
    </div>
  );
}

// a bulleted list inside prose, with the bullets outside the text column
export function BulletList({ children }: { children: ReactNode }) {
  return <ul className="list-disc space-y-2 pl-5 marker:text-surface-500">{children}</ul>;
}

export function Code({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-surface-100 px-1 py-0.5 font-mono text-[max(0.8125rem,0.9em)] text-surface-900 dark:bg-surface-800 dark:text-surface-50">
      {children}
    </code>
  );
}

export function CodeBlock({ children, label }: { children: string; label: string }) {
  return (
    <pre
      aria-label={label}
      tabIndex={0}
      className="overflow-x-auto rounded-lg border border-surface-200 bg-surface-100 p-4 font-mono text-base text-surface-900 dark:border-surface-800 dark:bg-surface-900 dark:text-surface-50"
    >
      <code>{children}</code>
    </pre>
  );
}
