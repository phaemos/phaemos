'use client';

import { openConsentPrompt } from '@/lib/consent';

// reopens the consent banner so a choice can be changed. Shown only when the
// site has an optional cookie (a Google Analytics id) to choose about.
export default function CookieSettingsButton({ className = '' }: { className?: string }) {
  if (!process.env.NEXT_PUBLIC_GA_ID) return null;
  return (
    <button
      type="button"
      onClick={openConsentPrompt}
      className={`inline-flex items-center min-h-[44px] min-w-[44px] underline underline-offset-2 hover:no-underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-700 dark:focus-visible:outline-brand-300 ${className}`}
    >
      Cookie settings
    </button>
  );
}
