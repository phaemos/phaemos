import Link from 'next/link';
import JsonLd from './JsonLd';
import { siteAbsolute } from '@/lib/links';

interface Crumb {
  name: string;
  href: string;
}

// where a nested page sits: Home, then its section, then the page itself as plain text marked as the current page. The
// separators are drawn with CSS and hidden from screen readers, which announce the list and its position instead. The
// same trail goes to search engines as BreadcrumbList data.
export default function Breadcrumbs({ trail, current }: { trail: Crumb[]; current: string }) {
  const all = [{ name: 'Home', href: '/' }, ...trail];
  const data = {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: [...all.map((c) => ({ name: c.name, item: siteAbsolute(c.href) })), { name: current }].map((c, i) => ({ '@type': 'ListItem', position: i + 1, ...c })),
  };
  return (
    <nav aria-label="Breadcrumb">
      <JsonLd data={data} />
      <ol className="flex flex-wrap items-center text-base">
        {all.map((c) => (
          <li key={c.href} className="flex items-center">
            <Link href={c.href} className="-mx-1 inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-md px-1 text-brand-800 underline underline-offset-2 hover:no-underline dark:text-brand-400">
              {c.name}
            </Link>
            <span aria-hidden="true" className="mx-2 text-surface-600 dark:text-surface-400">/</span>
          </li>
        ))}
        <li aria-current="page" className="min-w-0 break-words text-surface-700 dark:text-surface-300">
          {current}
        </li>
      </ol>
    </nav>
  );
}
