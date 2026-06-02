'use client';

import { useState, useEffect } from 'react';

const STORAGE_KEY = 'cookie_consent';

export default function CookieBanner() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    // Show only if consent hasn't been recorded yet.
    if (!localStorage.getItem(STORAGE_KEY)) {
      setVisible(true);
    }
  }, []);

  function accept() {
    localStorage.setItem(STORAGE_KEY, 'accepted');
    setVisible(false);
  }

  function decline() {
    localStorage.setItem(STORAGE_KEY, 'declined');
    setVisible(false);
  }

  if (!visible) return null;

  return (
    <div
      role="dialog"
      aria-label="Cookie consent"
      className="fixed bottom-0 left-0 right-0 z-50 bg-surface-900 border-t border-surface-700 px-4 py-4 sm:flex sm:items-center sm:justify-between sm:gap-6"
    >
      <p className="text-sm text-surface-300 mb-3 sm:mb-0">
        We use one strictly necessary cookie to keep you signed in (session management).
        No tracking or advertising cookies.{' '}
        <a href="/privacy#cookies" className="text-primary-400 hover:underline">
          Privacy Policy
        </a>
      </p>
      <div className="flex gap-2 flex-shrink-0">
        <button
          type="button"
          onClick={accept}
          className="px-4 py-2 bg-primary-600 hover:bg-primary-500 text-white text-sm font-medium rounded-lg transition-colors"
        >
          Accept
        </button>
        <button
          type="button"
          onClick={decline}
          className="px-4 py-2 bg-surface-700 hover:bg-surface-600 text-surface-200 text-sm font-medium rounded-lg transition-colors"
        >
          Decline
        </button>
      </div>
    </div>
  );
}
