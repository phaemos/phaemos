import Link from 'next/link';
import type { ReactNode } from 'react';
import { ExternalIcon } from '@/components/ui/icons';
import { cn } from '@/lib/cn';
import { SPLIT } from '@/lib/links';

const STYLE = 'text-brand-800 underline underline-offset-2 hover:no-underline dark:text-brand-400';

interface Props {
  href: string;
  children: ReactNode;
  className?: string;
  // the full address to print after the text on paper, for a link given as a path
  printHref?: string;
}

// a link in running text. It is always underlined (colour is never the only cue) and a link to another site opens
// in a new tab with the external mark and a spoken note. A mailto link and a link inside the site stay in place.
export default function TextLink({ href, children, className, printHref }: Props) {
  if (href.startsWith('/')) {
    return <Link href={href} data-print-href={printHref} className={cn(STYLE, className)}>{children}</Link>;
  }
  // the other half of this product (the site from the dashboard or the reverse) is not another site: same tab, no mark
  if (SPLIT.split && [SPLIT.siteOrigin, SPLIT.appOrigin].some((o) => href === o || href.startsWith(`${o}/`))) {
    return <a href={href} className={cn(STYLE, className)}>{children}</a>;
  }
  if (href.startsWith('mailto:') || href.startsWith('#')) {
    return <a href={href} className={cn(STYLE, className)}>{children}</a>;
  }
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={cn(STYLE, className)}>
      {children}
      <span className="ml-1 inline-block align-baseline"><ExternalIcon size={12} /></span>
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}
