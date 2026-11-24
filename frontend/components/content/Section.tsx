import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

interface Props {
  title: string;
  // ties the heading to the section for screen readers and gives the section an anchor
  id: string;
  children: ReactNode;
  className?: string;
}

// a page section: a hairline rule, an h2 and the content. The first section on a page has no rule above it;
// a section is a heading and spacing, never a box.
export default function Section({ title, id, children, className }: Props) {
  return (
    <section
      id={id}
      aria-labelledby={`${id}-title`}
      className={cn('scroll-mt-20 border-t border-surface-200 pt-8 dark:border-surface-800 [&:not(:first-child)]:mt-10 first:border-t-0 first:pt-0', className)}
    >
      <h2 id={`${id}-title`} className="mb-4 text-2xl font-semibold tracking-[-0.01em] text-surface-900 dark:text-surface-50">
        {title}
      </h2>
      {children}
    </section>
  );
}
