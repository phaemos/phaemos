'use client';

import { useEffect } from 'react';
import { ErrorPanel } from '@/components/ui/ErrorBoundary';

// an error in any signed-in page lands here, inside the shell, so the sidebar stays and the person can leave the page.
// reset re-renders the failed segment without a full reload.
export default function AppError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error('[app error]', error);
  }, [error]);
  return <ErrorPanel onReload={reset} />;
}
