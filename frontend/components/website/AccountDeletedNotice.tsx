'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

function Notice() {
  if (useSearchParams().get('account') !== 'deleted') return null;
  return (
    <div role="status" className="border-b border-surface-200 bg-surface-100 dark:border-surface-800 dark:bg-surface-900">
      <p className="mx-auto max-w-6xl px-4 py-3 text-base text-surface-900 dark:text-surface-50 sm:px-6">
        Your account was deleted and you are signed out. Tickets you raised stay, without your name on them.
      </p>
    </div>
  );
}

// where a person lands after deleting their account from the profile page. It says that it happened.
export default function AccountDeletedNotice() {
  return (
    <Suspense fallback={null}>
      <Notice />
    </Suspense>
  );
}
