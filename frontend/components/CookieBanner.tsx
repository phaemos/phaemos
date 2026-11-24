'use client';

import { useEffect, useId, useRef, useState, useSyncExternalStore } from 'react';
import {
  closeConsentPrompt,
  getPromptOpen,
  getServerConsent,
  getServerPromptOpen,
  readConsent,
  subscribeConsent,
  writeConsent,
} from '@/lib/consent';

// the three choices share one look, so none is easier to press than another
const choiceClass =
  'min-h-[44px] min-w-[44px] px-5 rounded-lg border-2 border-surface-700 dark:border-surface-300 bg-white dark:bg-surface-900 hover:bg-surface-100 dark:hover:bg-surface-800 text-surface-900 dark:text-surface-50 text-base font-medium';

const focusRing =
  'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-700 dark:focus-visible:outline-brand-300';

// the banner only exists when there is an optional cookie to ask about. Without a
// Google Analytics id the site sets only strictly necessary cookies, which need no
// consent, so there is nothing to accept or decline and the banner stays away.
export default function CookieBanner() {
  const consent = useSyncExternalStore(subscribeConsent, readConsent, getServerConsent);
  const reopened = useSyncExternalStore(subscribeConsent, getPromptOpen, getServerPromptOpen);
  const gaId = process.env.NEXT_PUBLIC_GA_ID;

  const panelRef = useRef<HTMLDivElement>(null);
  // the customise view: one switch per optional purpose. Analytics is the only one, so it is one checkbox, unticked
  // unless the visitor accepted before.
  const [customising, setCustomising] = useState(false);
  const [analyticsOn, setAnalyticsOn] = useState(false);
  const analyticsId = useId();
  const returnFocusTo = useRef<HTMLElement | null>(null);

  // unknown is the server render: waiting for the client read avoids a flash of
  // the banner for visitors who already chose.
  const visible = Boolean(gaId) && (consent === 'unset' || reopened);

  // the banner is fixed to the bottom of the screen, so the app shell reserves
  // its measured height through this variable. Nothing is hidden underneath it
  // and the end of every page can still be scrolled into view.
  useEffect(() => {
    const panel = panelRef.current;
    const root = document.documentElement;
    if (!visible || !panel) return;
    const publish = () => root.style.setProperty('--cookie-banner-height', `${panel.offsetHeight}px`);
    publish();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(publish);
    observer?.observe(panel);
    return () => {
      observer?.disconnect();
      root.style.removeProperty('--cookie-banner-height');
    };
  }, [visible]);

  useEffect(() => {
    if (!reopened) return;
    // opened from the settings button: move focus in so it is announced and
    // reachable, then hand it back to the button on close.
    returnFocusTo.current = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    return () => {
      // the page can be reloading by now, so only a button still in the page is focused
      const target = returnFocusTo.current;
      returnFocusTo.current = null;
      try {
        if (target?.isConnected) target.focus();
      } catch {
        // focus is a courtesy here, never a reason to fail
      }
    };
  }, [reopened]);

  if (!visible) return null;

  function choose(choice: 'accepted' | 'declined') {
    writeConsent(choice);
    setCustomising(false);
    closeConsentPrompt();
  }

  function openCustomise() {
    setAnalyticsOn(consent === 'accepted');
    setCustomising(true);
  }

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-modal="false"
      aria-labelledby="cookie-banner-title"
      aria-describedby="cookie-banner-text"
      tabIndex={-1}
      onKeyDown={(e) => {
        // closing without a choice only makes sense once a choice exists
        if (e.key === 'Escape' && consent !== 'unset') closeConsentPrompt();
      }}
      className="fixed bottom-0 left-0 right-0 z-50 border-t-4 border-surface-600 dark:border-surface-400 bg-white dark:bg-surface-900 text-surface-900 dark:text-surface-50 px-4 py-4 focus:outline-none sm:flex sm:items-center sm:justify-between sm:gap-6"
    >
      <div className="mb-3 sm:mb-0">
        {/* a paragraph, not a heading: the banner comes first in the page and a heading would land before the h1 */}
        <p id="cookie-banner-title" className="text-base font-semibold">
          Cookies and analytics
        </p>
        <p id="cookie-banner-text" className="mt-1 text-base text-surface-700 dark:text-surface-300">
          We use strictly necessary cookies to keep you signed in. If you accept, we also turn on
          Google Analytics, which sets cookies to count visits. If you reject them, Google Analytics stays
          off. You can change your choice at any time with Cookie settings.{' '}
          <a
            href="/cookies"
            className={`font-medium underline underline-offset-2 text-brand-800 dark:text-brand-300 hover:no-underline ${focusRing}`}
          >
            Cookies page
          </a>
        </p>
      </div>
      {customising ? (
        <fieldset className="shrink-0 space-y-3 sm:max-w-md">
          <legend className="sr-only">Choose which cookies to allow</legend>
          <p className="text-base text-surface-900 dark:text-surface-50">
            <span className="font-semibold">Strictly necessary:</span> always on. They keep you signed in and remember this choice.
          </p>
          <label htmlFor={analyticsId} className="flex min-h-[44px] cursor-pointer items-center gap-3 text-base text-surface-900 dark:text-surface-50">
            <input id={analyticsId} type="checkbox" checked={analyticsOn} onChange={(e) => setAnalyticsOn(e.target.checked)} />
            <span><span className="font-semibold">Analytics:</span> Google Analytics counts visits. Optional.</span>
          </label>
          <div className="flex flex-wrap gap-3">
            <button type="button" onClick={() => choose(analyticsOn ? 'accepted' : 'declined')} className={`${choiceClass} ${focusRing}`}>
              Save my choice
            </button>
            <button type="button" onClick={() => setCustomising(false)} className={`${choiceClass} ${focusRing}`}>
              Back
            </button>
          </div>
        </fieldset>
      ) : (
        <div className="flex shrink-0 flex-wrap gap-3">
          <button type="button" onClick={() => choose('accepted')} className={`${choiceClass} ${focusRing}`}>
            Accept all
          </button>
          <button type="button" onClick={() => choose('declined')} className={`${choiceClass} ${focusRing}`}>
            Reject non-essential
          </button>
          <button type="button" onClick={openCustomise} className={`${choiceClass} ${focusRing}`}>
            Customise
          </button>
        </div>
      )}
    </div>
  );
}
