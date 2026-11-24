'use client';

import { useEffect } from 'react';
import { ErrorPanel } from '@/components/ui/ErrorBoundary';

// the last resort for an error nothing nearer caught. It renders inside the root layout, which holds no shell, so it
// brings its own landmark. Routes under (app) have their own error file and keep the sidebar.
export default function RootError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error('[route error]', error);
  }, [error]);
  return (
    <main id="main" className="min-h-[calc(100dvh-var(--cookie-banner-height,0px))]">
      <ErrorPanel onReload={reset} />
    </main>
  );
}
