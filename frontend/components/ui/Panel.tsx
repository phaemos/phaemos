import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

interface Props {
  title?: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  // heading level for the title so a panel never breaks the page outline
  headingLevel?: 2 | 3;
  id?: string;
}

// the one surface every block of content sits on: a hairline border, 8 px corners and an optional header row;
// it wraps one discrete object and has no shadow in either theme.
export default function Panel({ title, description, actions, children, className, bodyClassName = 'p-4', headingLevel = 2, id }: Props) {
  const Heading = headingLevel === 2 ? 'h2' : 'h3';
  return (
    <section
      id={id}
      className={cn(
        'rounded-lg border border-surface-200 bg-surface-0 dark:border-surface-800 dark:bg-surface-900',
        className,
      )}
    >
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-surface-200 px-4 py-3 dark:border-surface-800">
          <div className="min-w-0">
            {title && <Heading className="text-base font-semibold text-surface-900 dark:text-surface-50">{title}</Heading>}
            {description && <p className="mt-0.5 text-meta text-surface-600 dark:text-surface-400">{description}</p>}
          </div>
          {actions}
        </header>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}
