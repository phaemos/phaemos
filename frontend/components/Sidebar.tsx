'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useRef, type ComponentType } from 'react';
import Logo from '@/components/ui/Logo';
import { appPath, isOverviewPath, siteHref } from '@/lib/links';
import UserMenu from '@/components/shell/UserMenu';
import FleetStatus from '@/components/shell/FleetStatus';
import {
  AdminIcon, AlertsIcon, ChangelogIcon, CloseIcon, CompareIcon, DevicesIcon, DocsIcon, ModelsIcon, OverviewIcon, TicketsIcon,
} from '@/components/ui/icons';
import type { ShellStale, ShellStatus, ShellUser } from '@/hooks/useShellStatus';

interface Item {
  href: string;
  label: string;
  Icon: ComponentType<{ size?: number }>;
  adminOnly?: boolean;
  // a page of the public site: with two addresses it is an absolute link to the site
  site?: boolean;
  badge?: boolean;
}

const GROUPS: { label: string; items: Item[] }[] = [
  {
    label: 'Monitor',
    items: [
      { href: '/dashboard', label: 'Overview', Icon: OverviewIcon },
      { href: '/devices', label: 'Machines', Icon: DevicesIcon },
      { href: '/compare', label: 'Compare', Icon: CompareIcon },
      { href: '/models', label: 'Models', Icon: ModelsIcon },
    ],
  },
  {
    label: 'Respond',
    items: [
      { href: '/alerts', label: 'Alerts', Icon: AlertsIcon, badge: true },
      { href: '/tickets', label: 'Tickets', Icon: TicketsIcon },
    ],
  },
  {
    label: 'Manage',
    items: [{ href: '/admin', label: 'Admin', Icon: AdminIcon, adminOnly: true }],
  },
];

const BOTTOM: Item[] = [
  { href: '/docs', label: 'Documentation', Icon: DocsIcon, site: true },
  { href: '/changelog', label: 'Changelog', Icon: ChangelogIcon, site: true },
];

interface Props {
  user: ShellUser | null;
  status: ShellStatus | null;
  // set while the shell's reads have stopped answering: the fleet line and the alert count are then unknown
  stale?: ShellStale | null;
  // below 768 px the sidebar is a drawer: open says whether it shows and onClose hides it
  open: boolean;
  onClose: (returnFocus?: boolean) => void;
}

// 240 px with labels, a 64 px icon rail between 768 and 1024 px and a drawer below 768 px. In the rail the
// labels stay in the page for screen readers and the group labels give way to a hairline.
export default function Sidebar({ user, status, stale, open, onClose }: Props) {
  const pathname = usePathname();
  const ref = useRef<HTMLElement>(null);

  // the current page: an exact match or any page under it, so a machine page keeps Machines marked
  const isCurrent = (href: string) => (href === '/dashboard' ? isOverviewPath(pathname) : pathname === href || pathname.startsWith(href + '/'));

  // as a drawer, focus moves in when it opens and Tab stays inside it. Escape handling and returning focus
  // to the menu button live in AppShell, which owns that button.
  useEffect(() => {
    if (!open) return;
    const isDrawer = window.matchMedia('(max-width: 767px)').matches;
    if (!isDrawer) return;
    ref.current?.querySelector<HTMLElement>('a,button')?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return;
      const nodes = Array.from(ref.current?.querySelectorAll<HTMLElement>('a,button') ?? []);
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open]);

  const row = (item: Item) => {
    const current = isCurrent(item.href);
    const count = item.badge && !stale ? status?.activeAlerts ?? 0 : 0;
    const unknown = Boolean(item.badge && stale);
    return (
      <li key={item.href}>
        <Link
          href={item.site ? siteHref(item.href) : appPath(item.href)}
          onClick={() => onClose()}
          aria-current={current ? 'page' : undefined}
          className={`relative flex min-h-[44px] items-center gap-3 rounded-md px-3 text-base no-underline md:max-lg:justify-center md:max-lg:px-0 ${
            current
              ? 'bg-surface-100 font-semibold text-surface-900 before:absolute before:inset-y-2 before:-left-1 before:w-[3px] before:rounded-full before:bg-brand-600 dark:bg-surface-800 dark:text-surface-50 dark:before:bg-brand-400'
              : 'font-medium text-surface-700 hover:bg-surface-100 hover:text-surface-900 dark:text-surface-300 dark:hover:bg-surface-800 dark:hover:text-surface-50'
          }`}
        >
          <item.Icon />
          <span className="flex-1 md:max-lg:sr-only">{item.label}</span>
          {unknown && (
            <span className="tnum min-w-[22px] rounded-full border border-surface-600 px-1.5 text-center text-meta font-semibold leading-5 text-surface-800 dark:border-surface-400 dark:text-surface-200 md:max-lg:absolute md:max-lg:right-1 md:max-lg:top-1">
              ?
              <span className="sr-only"> alert count unknown</span>
            </span>
          )}
          {count > 0 && (
            <span className="tnum min-w-[22px] rounded-full bg-critical-800 px-1.5 text-center text-meta font-semibold leading-5 text-white md:max-lg:absolute md:max-lg:right-1 md:max-lg:top-1 md:max-lg:min-w-[18px] md:max-lg:px-1 md:max-lg:text-meta md:max-lg:leading-[18px]">
              {count > 99 ? '99+' : count}
              <span className="sr-only"> active</span>
            </span>
          )}
        </Link>
      </li>
    );
  };

  return (
    <aside
      ref={ref}
      aria-label="Sidebar"
      className={`${open ? 'drawer-in max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-50 max-md:flex max-md:w-72' : 'max-md:hidden'} shrink-0 flex-col border-r border-surface-200 bg-surface-0 dark:border-surface-800 dark:bg-surface-900 md:flex md:w-16 lg:w-60`}
    >
      <div className="flex h-12 shrink-0 items-center justify-between border-b border-surface-200 px-4 dark:border-surface-800 md:max-lg:justify-center md:max-lg:px-0">
        <Link href={siteHref('/')} className="inline-flex min-h-[44px] items-center gap-2.5 rounded-md no-underline focus-visible:outline-offset-[-2px] md:max-lg:min-w-[44px] md:max-lg:justify-center" aria-label="PHAEMOS home">
          <span className="hidden md:max-lg:inline-flex"><Logo showWord={false} /></span>
          <span className="inline-flex items-center gap-2.5 md:max-lg:hidden"><Logo /></span>
        </Link>
        <button
          type="button"
          onClick={() => onClose(true)}
          aria-label="Close menu"
          className="inline-flex items-center justify-center rounded-md text-surface-700 hover:bg-surface-100 focus-visible:outline-offset-[-2px] dark:text-surface-300 dark:hover:bg-surface-800 md:hidden"
        >
          <CloseIcon />
        </button>
      </div>

      {/* from 1024 px the fleet status lives here. The rail has no room for it and the bar shows it below 1024 px, so it is hidden in the rail. */}
      <div className="shrink-0 border-b border-surface-200 px-4 py-2.5 dark:border-surface-800 md:max-lg:hidden">
        <FleetStatus status={status} stale={stale} />
      </div>

      <nav aria-label="Dashboard" className="flex-1 overflow-y-auto px-3 py-3 md:max-lg:px-2">
        {GROUPS.map((g) => {
          const items = g.items.filter((i) => !i.adminOnly || user?.role === 'admin');
          if (items.length === 0) return null;
          const id = `nav-${g.label.toLowerCase()}`;
          return (
            <div key={g.label} role="group" aria-labelledby={id} className="mb-4">
              <div id={id} className="label mb-1 px-3 text-surface-700 dark:text-surface-300 md:max-lg:sr-only">{g.label}</div>
              <div className="mx-2 mb-1 hidden border-t border-surface-200 dark:border-surface-800 md:max-lg:block" aria-hidden="true" />
              <ul className="space-y-0.5">{items.map(row)}</ul>
            </div>
          );
        })}
      </nav>

      <div className="shrink-0 space-y-2 border-t border-surface-200 px-3 py-3 dark:border-surface-800 md:max-lg:px-2">
        <nav aria-label="Reference">
          <ul className="space-y-0.5">{BOTTOM.map(row)}</ul>
        </nav>
        <UserMenu user={user} onNavigate={() => onClose()} />
      </div>
    </aside>
  );
}
