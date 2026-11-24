'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Sidebar from '@/components/Sidebar';
import TopBar from '@/components/shell/TopBar';
import ErrorBoundary from '@/components/ui/ErrorBoundary';
import { useShellStatus } from '@/hooks/useShellStatus';
import { isLeaving, listenForSignOut } from '@/lib/session';
import { nextFor } from '@/lib/publicPaths';

// the dashboard shell: sidebar, a 48 px top bar and the page. It ends above the cookie banner, which publishes its
// height in --cookie-banner-height while it shows. Below 768 px the sidebar is a drawer that this component opens.
export default function AppShell({ children }: { children: React.ReactNode }) {
  const { status, user, stale } = useShellStatus();
  const [drawer, setDrawer] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);

  // a sign-out in another tab ends this session as well, so this tab leaves at once and not at its next poll
  useEffect(
    () =>
      listenForSignOut(() => {
        // this tab started the sign-out itself and is already on its way somewhere
        if (isLeaving()) return;
        const next = nextFor(window.location.pathname, window.location.search);
        const login = new URL('/login', window.location.origin);
        if (next) login.searchParams.set('next', next);
        window.location.replace(login.href);
      }),
    [],
  );

  const close = useCallback((returnFocus?: boolean) => {
    setDrawer(false);
    // the page behind the drawer is inert until this render commits, so focus goes back on the next tick
    if (returnFocus) setTimeout(() => menuButton.current?.focus(), 0);
  }, []);

  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        close(true);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [drawer, close]);

  return (
    <div className="flex h-[calc(100dvh-var(--cookie-banner-height,0px))] overflow-hidden">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-[60] focus:rounded-lg focus:bg-brand-700 focus:px-4 focus:py-3 focus:text-white">
        Skip to content
      </a>
      <div id="app-sidebar" className="contents">
        <Sidebar user={user} status={status} stale={stale} open={drawer} onClose={close} />
      </div>
      {drawer && <div className="fade-in fixed inset-0 z-40 bg-surface-950/60 md:hidden" onClick={() => close(true)} aria-hidden="true" />}
      {/* inert while the drawer is open so the page behind it cannot take focus */}
      <div className="flex min-w-0 flex-1 flex-col" inert={drawer || undefined}>
        <TopBar ref={menuButton} status={status} stale={stale} menuOpen={drawer} onMenu={() => setDrawer(true)} />
        <main id="main" tabIndex={-1} className="flex-1 overflow-y-auto outline-none">
          {/* the one outer box for every signed-in page: the same padding and the same left edge. Pages add only their own spacing. */}
          <div className="max-w-7xl p-6">
            <ErrorBoundary>{children}</ErrorBoundary>
          </div>
        </main>
      </div>
    </div>
  );
}
