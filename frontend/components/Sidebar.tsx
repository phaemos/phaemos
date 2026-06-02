'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import ThemeToggle from '@/components/ui/ThemeToggle';
import LogoutButton from '@/components/ui/LogoutButton';

const NAV_LINKS = [
  { href: '/',        label: 'Dashboard' },
  { href: '/compare', label: 'Compare' },
  { href: '/alerts',  label: 'Alerts' },
  { href: '/tickets', label: 'Tickets' },
  { href: '/devices', label: 'Devices' },
  { href: '/admin',   label: 'Admin' },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-60 shrink-0 flex flex-col h-screen bg-surface-50 dark:bg-surface-900 border-r border-surface-200 dark:border-surface-800">
      <div className="px-5 py-5">
        <span className="text-sm font-bold tracking-tight text-surface-900 dark:text-surface-50">
          PHAEMOS
        </span>
      </div>

      <nav className="flex-1 overflow-y-auto py-2">
        {NAV_LINKS.map(({ href, label }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={`px-4 py-2.5 rounded-r-lg text-sm font-medium flex items-center gap-3 transition-colours duration-150 ${
                active
                  ? 'border-l-4 border-brand-500 bg-brand-50 dark:bg-brand-900/20 text-brand-600 dark:text-brand-400'
                  : 'text-surface-600 dark:text-surface-400 hover:bg-surface-100 dark:hover:bg-surface-800 hover:text-surface-900 dark:hover:text-surface-50'
              }`}
            >
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="px-4 py-4 border-t border-surface-200 dark:border-surface-800 space-y-3">
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <LogoutButton />
        </div>
        <div className="flex items-center gap-3 text-xs text-surface-400 dark:text-surface-600">
          <a href="/privacy" className="hover:text-surface-600 dark:hover:text-surface-400 transition-colours">Privacy</a>
          <a href="/terms"   className="hover:text-surface-600 dark:hover:text-surface-400 transition-colours">Terms</a>
          <a href="/status"  className="hover:text-surface-600 dark:hover:text-surface-400 transition-colours">Status</a>
        </div>
      </div>
    </aside>
  );
}
