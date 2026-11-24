import type { ReactNode } from 'react';

interface Props {
  title: string;
  // one sentence saying what the page holds
  lead?: ReactNode;
  className?: string;
}

// the head of a public page: the h1 at 36 px on phones and 48 px from 768 px, then one lead sentence at 16 or 18 px;
// a heading says what the page is on its own, so there is no label above it. The text column stops at 72 characters. Every public page uses this and nothing else.
export default function SiteHeading({ title, lead, className = '' }: Props) {
  return (
    <header className={className}>
      <h1 className="max-w-[24ch] text-4xl font-semibold tracking-[-0.02em] text-surface-900 dark:text-surface-50 md:text-5xl">{title}</h1>
      {lead && <p className="mt-4 max-w-[72ch] text-base text-surface-700 dark:text-surface-300 md:text-lg">{lead}</p>}
    </header>
  );
}
