import Link from 'next/link';
import CookieSettingsButton from '@/components/CookieSettingsButton';
import Logo from '@/components/ui/Logo';
import { ExternalIcon } from '@/components/ui/icons';
import { REPO_URL } from '@/lib/site';

const linkClass =
  'inline-flex min-h-[44px] min-w-[44px] items-center text-base text-surface-700 hover:text-surface-900 hover:underline dark:text-surface-300 dark:hover:text-surface-50';

const COLUMNS: { title: string; links: { href: string; label: string; external?: boolean }[] }[] = [
  {
    title: 'Product',
    links: [
      { href: '/about', label: 'About' },
      { href: '/changelog', label: 'Changelog' },
      { href: '/status', label: 'Status' },
    ],
  },
  {
    title: 'Resources',
    links: [
      { href: '/docs', label: 'Documentation' },
      { href: '/blog', label: 'Blog' },
      { href: '/faq', label: 'FAQ' },
      { href: '/support', label: 'Support' },
    ],
  },
  {
    title: 'Project',
    links: [
      { href: REPO_URL, label: 'GitHub', external: true },
      { href: '/contact', label: 'Contact' },
    ],
  },
];

export default function SiteFooter() {
  return (
    <footer className="border-t border-surface-200 bg-surface-0 dark:border-surface-800 dark:bg-surface-900">
      <div className="mx-auto grid max-w-6xl grid-cols-2 gap-x-8 gap-y-4 px-4 py-6 sm:px-6 md:grid-cols-[1.4fr_repeat(4,1fr)]">
        <div className="col-span-2 space-y-2 md:col-span-1">
          <Link href="/" className="inline-flex min-h-[44px] items-center gap-2.5 no-underline" aria-label="PHAEMOS home">
            <Logo />
          </Link>
          <p className="max-w-xs text-base text-surface-600 dark:text-surface-400">Open industrial IoT platform for predictive maintenance.</p>
          <p className="max-w-xs text-meta text-surface-600 dark:text-surface-400">Free software under the GNU Affero General Public License v3.0 or later.</p>
        </div>

        {COLUMNS.map((col) => (
          <nav key={col.title} aria-label={col.title}>
            <p className="label mb-1 text-surface-700 dark:text-surface-300">{col.title}</p>
            <ul>
              {col.links.map((l) => (
                <li key={l.href}>
                  {l.external ? (
                    <a href={l.href} target="_blank" rel="noopener noreferrer" className={linkClass}>
                      {l.label}
                      <ExternalIcon className="ml-1.5" />
                      <span className="sr-only"> (opens in a new tab)</span>
                    </a>
                  ) : (
                    <Link href={l.href} className={linkClass}>{l.label}</Link>
                  )}
                </li>
              ))}
            </ul>
          </nav>
        ))}

        <nav aria-label="Legal">
          <p className="label mb-1 text-surface-700 dark:text-surface-300">Legal</p>
          <ul>
            <li><Link href="/privacy" className={linkClass}>Privacy</Link></li>
            <li><Link href="/cookies" className={linkClass}>Cookies</Link></li>
            <li><Link href="/terms" className={linkClass}>Terms</Link></li>
            <li><Link href="/security" className={linkClass}>Security</Link></li>
            <li><Link href="/accessibility" className={linkClass}>Accessibility</Link></li>
            <li>
              <CookieSettingsButton className="text-base text-surface-700 dark:text-surface-300" />
            </li>
          </ul>
        </nav>
      </div>
    </footer>
  );
}
