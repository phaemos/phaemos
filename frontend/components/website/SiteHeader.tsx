'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';
import Button from '@/components/ui/Button';
import Logo from '@/components/ui/Logo';
import ThemeToggle from '@/components/ui/ThemeToggle';
import { CloseIcon, ExternalIcon, MenuIcon } from '@/components/ui/icons';
import { useSignedIn } from '@/hooks/useSignedIn';
import { dashboardCta } from '@/lib/links';
import { REPO_URL } from '@/lib/site';
import { track } from '@/lib/analytics';

const LINKS = [
  { href: '/about', label: 'About' },
  { href: '/docs', label: 'Documentation' },
  { href: '/changelog', label: 'Changelog' },
  { href: '/blog', label: 'Blog' },
  { href: '/status', label: 'Status' },
];

const linkClass = (active: boolean) =>
  `inline-flex min-h-[44px] items-center rounded-md px-3 text-base font-medium no-underline ${
    active
      ? 'text-surface-900 dark:text-surface-50'
      : 'text-surface-700 hover:bg-surface-100 hover:text-surface-900 dark:text-surface-300 dark:hover:bg-surface-800 dark:hover:text-surface-50'
  }`;

// sticky 56 px top nav. Above 768 px the links sit in the bar and below it they fold into a menu button
// that opens a full-width panel: focus moves in, Escape closes and focus goes back to the button.
export default function SiteHeader() {
  const pathname = usePathname();
  const signedIn = useSignedIn();
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const close = useCallback((returnFocus: boolean) => {
    setOpen(false);
    if (returnFocus) buttonRef.current?.focus();
  }, []);

  // a link in the panel navigates, so the panel closes without grabbing focus back
  useEffect(() => {
    // closing on a route change, the documented effect pattern for syncing with an external change
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!open) return;
    panelRef.current?.querySelector<HTMLElement>('a,button')?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        close(true);
        return;
      }
      // keep Tab inside the open panel and its button
      if (e.key === 'Tab') {
        const nodes = [buttonRef.current, ...Array.from(panelRef.current?.querySelectorAll<HTMLElement>('a,button') ?? [])].filter(Boolean) as HTMLElement[];
        const first = nodes[0];
        const last = nodes[nodes.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, close]);

  const cta = dashboardCta(signedIn);
  const isActive = (href: string) => pathname === href || pathname.startsWith(href + '/');

  return (
    <header className="sticky top-0 z-40 min-h-14 border-b border-surface-200 bg-surface-50 dark:border-surface-800 dark:bg-surface-950">
      {/* a row that may wrap: with text enlarged the nav and the buttons drop to a second line and never leave the screen */}
      <div className="mx-auto flex min-h-14 max-w-6xl flex-wrap items-center gap-x-2 px-4 py-1 sm:px-6">
        <Link href="/" className="mr-2 inline-flex min-h-[44px] items-center gap-2.5 rounded-lg no-underline" aria-label="PHAEMOS home">
          <Logo />
        </Link>

        <nav aria-label="Main" className="hidden lg:block">
          <ul className="flex flex-wrap items-center gap-1">
            {LINKS.map((l) => (
              <li key={l.href}>
                <Link href={l.href} aria-current={isActive(l.href) ? 'page' : undefined} className={linkClass(isActive(l.href))}>
                  {l.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>

        <div className="ml-auto flex flex-wrap items-center gap-1">
          <a
            href={REPO_URL}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => track('repository_opened', { place: 'header' })}
            className={`${linkClass(false)} max-lg:hidden gap-1.5`}
          >
            GitHub
            <ExternalIcon />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
          <ThemeToggle />
          <Button href={cta.href} className="ml-1 hidden lg:inline-flex">{cta.label}</Button>
          <button
            ref={buttonRef}
            type="button"
            aria-expanded={open}
            aria-controls="site-menu"
            aria-label={open ? 'Close menu' : 'Open menu'}
            onClick={() => (open ? close(false) : setOpen(true))}
            className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-md text-surface-700 hover:bg-surface-100 dark:text-surface-300 dark:hover:bg-surface-800 lg:hidden"
          >
            {open ? <CloseIcon /> : <MenuIcon />}
          </button>
        </div>
      </div>

      {open && (
        <div
          id="site-menu"
          ref={panelRef}
          className="absolute inset-x-0 top-full max-h-[calc(100dvh-3.5rem)] overflow-y-auto border-b border-surface-200 bg-surface-50 px-4 py-3 dark:border-surface-800 dark:bg-surface-950 lg:hidden"
        >
          <nav aria-label="Mobile">
            <ul className="flex flex-col">
              {LINKS.map((l) => (
                <li key={l.href}>
                  <Link href={l.href} aria-current={isActive(l.href) ? 'page' : undefined} className={`${linkClass(isActive(l.href))} w-full`}>
                    {l.label}
                  </Link>
                </li>
              ))}
              <li>
                <a href={REPO_URL} target="_blank" rel="noopener noreferrer"
            onClick={() => track('repository_opened', { place: 'header' })} className={`${linkClass(false)} w-full gap-1.5`}>
                  GitHub
                  <ExternalIcon />
                  <span className="sr-only">(opens in a new tab)</span>
                </a>
              </li>
            </ul>
          </nav>
          <Button href={cta.href} className="mt-3 w-full">{cta.label}</Button>
        </div>
      )}
    </header>
  );
}
