'use client';

import { forwardRef } from 'react';
import { MenuIcon } from '@/components/ui/icons';
import FleetStatus from '@/components/shell/FleetStatus';
import type { ShellStale, ShellStatus } from '@/hooks/useShellStatus';


// only below 1024 px. From 1024 px the page's own h1 is the title and the fleet status lives in the sidebar, so a
// bar would repeat both. Here it holds the menu button and the fleet status. The page's own h1 names the page, so the bar does not repeat it.
const TopBar = forwardRef<HTMLButtonElement, { status: ShellStatus | null; stale?: ShellStale | null; onMenu: () => void; menuOpen: boolean }>(function TopBar({ status, stale, onMenu, menuOpen }, ref) {
  return (
    <header className="flex h-12 shrink-0 items-center gap-2 border-b border-surface-200 bg-surface-0 px-3 dark:border-surface-800 dark:bg-surface-900 sm:px-5 lg:hidden">
      <button
        ref={ref}
        type="button"
        onClick={onMenu}
        aria-label="Open menu"
        aria-expanded={menuOpen}
        aria-controls="app-sidebar"
        className="inline-flex items-center justify-center rounded-md focus-visible:outline-offset-[-2px] text-surface-700 hover:bg-surface-100 dark:text-surface-300 dark:hover:bg-surface-800 md:hidden"
      >
        <MenuIcon />
      </button>
      <div className="ml-auto"><FleetStatus status={status} stale={stale} /></div>
    </header>
  );
});

export default TopBar;
