'use client';

import Image from 'next/image';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import ThemeToggle from '@/components/ui/ThemeToggle';
import LogoutButton from '@/components/ui/LogoutButton';

const NAV_LINKS = [
  { href: '/',          label: 'Dashboard' },
  { href: '/compare',   label: 'Compare' },
  { href: '/alerts',    label: 'Alerts' },
  { href: '/tickets',   label: 'Tickets' },
  { href: '/devices',   label: 'Devices' },
  { href: '/admin',     label: 'Admin' },
];

const BOTTOM_NAV_LINKS = [
  { href: '/changelog', label: 'Changelog' },
  { href: '/docs',      label: 'Docs' },
];

export default function Sidebar() {
  const pathname = usePathname();

  // the sign-in page stands alone: app navigation and a sign-out button mean nothing before signing in
  if (pathname === '/login') return null;

  return (
    <aside className="w-60 shrink-0 flex flex-col h-screen bg-surface-50 dark:bg-surface-900 border-r border-surface-200 dark:border-surface-800">
      <div className="px-5 py-5">
        <Link href="/" className="flex items-center gap-2.5">
          <span className="inline-flex shrink-0" aria-hidden="true">
            {/* the light mark sits on light surfaces and the dark mark on dark ones */}
            <Image src="/brand/phaemos-emblem-light.png" alt="" width={28} height={28} className="dark:hidden" />
            <Image src="/brand/phaemos-emblem-dark.png" alt="" width={28} height={28} className="hidden dark:block" />
          </span>
          <span className="text-sm font-bold tracking-tight text-surface-900 dark:text-surface-50">
            PHAEMOS
          </span>
        </Link>
      </div>

      <nav className="flex-1 overflow-y-auto py-2">
        {NAV_LINKS.map(({ href, label }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={`px-4 py-2.5 rounded-r-lg text-sm font-medium flex items-center gap-3 transition-colors duration-150 ${
                active
                  ? 'border-l-4 border-brand-500 bg-brand-50 dark:bg-brand-900/20 text-brand-600 dark:text-brand-400'
                  : 'text-surface-600 dark:text-surface-400 hover:bg-surface-100 dark:hover:bg-surface-800 hover:text-surface-900 dark:hover:text-surface-50'
              }`}
            >
              {label}
            </Link>
          );
        })}
        <div className="mt-2 pt-2 border-t border-surface-200 dark:border-surface-800">
          {BOTTOM_NAV_LINKS.map(({ href, label }) => {
            const active = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                className={`px-4 py-2 rounded-r-lg text-xs font-medium flex items-center gap-3 transition-colors duration-150 ${
                  active
                    ? 'border-l-4 border-brand-500 bg-brand-50 dark:bg-brand-900/20 text-brand-600 dark:text-brand-400'
                    : 'text-surface-500 dark:text-surface-500 hover:bg-surface-100 dark:hover:bg-surface-800 hover:text-surface-700 dark:hover:text-surface-300'
                }`}
              >
                {label}
              </Link>
            );
          })}
        </div>
      </nav>

      <div className="px-4 py-4 border-t border-surface-200 dark:border-surface-800 space-y-3">
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <LogoutButton />
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-surface-400 dark:text-surface-600">
          <Link href="/about"    className="hover:text-surface-600 dark:hover:text-surface-400 transition-colors">About</Link>
          <Link href="/blog"     className="hover:text-surface-600 dark:hover:text-surface-400 transition-colors">Blog</Link>
          <Link href="/privacy"  className="hover:text-surface-600 dark:hover:text-surface-400 transition-colors">Privacy</Link>
          <Link href="/terms"    className="hover:text-surface-600 dark:hover:text-surface-400 transition-colors">Terms</Link>
          <Link href="/security" className="hover:text-surface-600 dark:hover:text-surface-400 transition-colors">Security</Link>
          <Link href="/faq"      className="hover:text-surface-600 dark:hover:text-surface-400 transition-colors">FAQ</Link>
          <Link href="/support"  className="hover:text-surface-600 dark:hover:text-surface-400 transition-colors">Support</Link>
          <Link href="/contact"  className="hover:text-surface-600 dark:hover:text-surface-400 transition-colors">Contact</Link>
          <Link href="/status"   className="hover:text-surface-600 dark:hover:text-surface-400 transition-colors">Status</Link>
        </div>
      </div>
    </aside>
  );
}
