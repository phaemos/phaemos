'use client';

// the theme class on the html element is set by the inline script in layout.tsx before the page paints. The icon and the
// words come from that class through CSS, not from state that arrives after hydration, so the right ones show at once
// and nothing shifts. The button reads the class again when it is pressed, so it never works from a stale copy.

import { THEME_COLOR } from '@/lib/theme';
import { MoonIcon, SunIcon } from './icons';

interface Props {
  // "bar" is an icon button for a header. "menu" is a full-width row with the words, for the user menu.
  variant?: 'bar' | 'menu';
  className?: string;
}

function toggleTheme() {
  const root = document.documentElement;
  const next = !root.classList.contains('dark');
  root.classList.toggle('dark', next);
  localStorage.setItem('theme', next ? 'dark' : 'light');
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', next ? THEME_COLOR.dark : THEME_COLOR.light);
}

// pressing it switches to the other theme, so a sun shows while the dark theme is on and a moon while the light one is
function Face() {
  return (
    <>
      <span className="hidden dark:inline-flex" aria-hidden="true"><SunIcon /></span>
      <span className="inline-flex dark:hidden" aria-hidden="true"><MoonIcon /></span>
    </>
  );
}

export default function ThemeToggle({ variant = 'bar', className = '' }: Props) {
  if (variant === 'menu') {
    return (
      <button
        type="button"
        role="menuitem"
        onClick={toggleTheme}
        className={`flex w-full items-center gap-3 rounded-md px-3 text-left text-base text-surface-800 hover:bg-surface-100 dark:text-surface-200 dark:hover:bg-surface-800 ${className}`}
      >
        <Face />
        <span className="dark:hidden">Switch to dark theme</span>
        <span className="hidden dark:inline">Switch to light theme</span>
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={toggleTheme}
      className={`inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-md text-surface-700 hover:bg-surface-100 hover:text-surface-900 dark:text-surface-300 dark:hover:bg-surface-800 dark:hover:text-surface-50 ${className}`}
    >
      <Face />
      {/* display: none hides the other name from assistive technology, so exactly one is read */}
      <span className="sr-only dark:hidden">Switch to dark theme</span>
      <span className="sr-only hidden dark:inline">Switch to light theme</span>
    </button>
  );
}
