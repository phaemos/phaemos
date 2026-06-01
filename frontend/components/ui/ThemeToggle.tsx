'use client';

// I read the current theme from the html element's class list (set by the
// inline script in layout.tsx) so the button reflects the real state even
// before React hydration completes.

import { useState, useEffect } from 'react';

export default function ThemeToggle() {
  const [dark, setDark] = useState(true);

  useEffect(() => {
    // I sync with the class applied by the pre-hydration script so the initial
    // button label matches what the user already sees.
    setDark(document.documentElement.classList.contains('dark'));
  }, []);

  const toggle = () => {
    const next = !dark;
    setDark(next);
    if (next) {
      document.documentElement.classList.add('dark');
      localStorage.setItem('theme', 'dark');
    } else {
      document.documentElement.classList.remove('dark');
      localStorage.setItem('theme', 'light');
    }
  };

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label="Toggle dark mode"
      className="px-2 py-1 rounded text-xs font-medium bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-100 transition-colours"
    >
      {dark ? 'Light' : 'Dark'}
    </button>
  );
}
