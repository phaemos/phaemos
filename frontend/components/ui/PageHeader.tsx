// a page's title, a line saying what the page is for and its controls, laid out the same everywhere in the app:
// the h1 is 20 px semibold and the description 14 px. Public pages use SiteHeading. `variant="site"` still works
// for callers written before SiteHeading existed and renders the same 36 to 48 px heading.
import type { ReactNode } from 'react';

interface Props {
  title: string;
  description?: string;
  actions?: ReactNode;
  variant?: 'app' | 'site';
}

export default function PageHeader({ title, description, actions, variant = 'app' }: Props) {
  const site = variant === 'site';
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1
          className={
            site
              ? 'text-4xl font-semibold tracking-[-0.02em] text-surface-900 dark:text-surface-50 md:text-5xl'
              : 'font-display text-xl font-semibold text-surface-900 dark:text-surface-50'
          }
        >
          {title}
        </h1>
        {description && <p className={`mt-1 max-w-[72ch] text-surface-600 dark:text-surface-400 ${site ? 'text-base md:text-lg' : 'text-base'}`}>{description}</p>}
      </div>
      {actions && <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
