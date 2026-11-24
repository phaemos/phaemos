'use client';

import Link from 'next/link';
import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import LogoutButton from '@/components/ui/LogoutButton';
import ThemeToggle from '@/components/ui/ThemeToggle';
import { ChevronIcon, UserIcon } from '@/components/ui/icons';
import type { ShellUser } from '@/hooks/useShellStatus';
import { roleWord } from '@/lib/format';

// the user row at the bottom of the sidebar. It opens a menu with Profile, the theme toggle and Sign out. There
// are no cookie settings here: analytics runs on the public site only. Arrow keys move between items, Escape closes and focus returns to the row.
export default function UserMenu({ user, onNavigate }: { user: ShellUser | null; onNavigate?: () => void }) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const items = () => Array.from(menuRef.current?.querySelectorAll<HTMLElement>('a,button') ?? []);

  useEffect(() => {
    if (!open) return;
    items()[0]?.focus();
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const list = items();
    const i = list.indexOf(document.activeElement as HTMLElement);
    if (e.key === 'Escape') {
      e.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      list[(i + 1) % list.length]?.focus();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      list[(i - 1 + list.length) % list.length]?.focus();
    } else if (e.key === 'Home') {
      e.preventDefault();
      list[0]?.focus();
    } else if (e.key === 'End') {
      e.preventDefault();
      list[list.length - 1]?.focus();
    } else if (e.key === 'Tab') {
      // leaving the menu with Tab closes it
      setOpen(false);
    }
  }

  const label = user?.name || user?.email || 'Account';
  const initial = label.charAt(0).toUpperCase();

  return (
    <div ref={wrapRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account menu for ${label}`}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 rounded-md px-2 text-left hover:bg-surface-100 dark:hover:bg-surface-800"
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-surface-300 bg-surface-100 text-meta font-semibold text-surface-800 dark:border-surface-600 dark:bg-surface-800 dark:text-surface-200" aria-hidden="true">
          {user ? initial : <UserIcon size={16} />}
        </span>
        <span className="min-w-0 flex-1 md:max-lg:sr-only">
          <span className="block truncate text-base font-medium text-surface-900 dark:text-surface-50">{label}</span>
          {user && <span className="block truncate text-meta text-surface-600 dark:text-surface-400">{roleWord(user.role)}</span>}
        </span>
        <span className="md:max-lg:hidden" aria-hidden="true"><ChevronIcon size={16} /></span>
      </button>

      {open && (
        <div
          ref={menuRef}
          role="menu"
          aria-label="Account"
          onKeyDown={onKeyDown}
          className="absolute bottom-full left-0 z-50 mb-2 w-60 rounded-md border border-surface-300 bg-surface-0 p-1 dark:border-surface-700 dark:bg-surface-900"
        >
          <Link
            href="/profile"
            role="menuitem"
            onClick={() => { setOpen(false); onNavigate?.(); }}
            className="flex min-h-[44px] items-center rounded-md px-3 text-base text-surface-800 no-underline hover:bg-surface-100 dark:text-surface-200 dark:hover:bg-surface-800"
          >
            Profile
          </Link>
          <ThemeToggle variant="menu" />
          <div className="my-1 border-t border-surface-200 dark:border-surface-800" role="none" />
          <LogoutButton variant="menu" />
        </div>
      )}
    </div>
  );
}
