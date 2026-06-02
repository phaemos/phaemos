'use client';

// I auto-dismiss after 4 seconds because error toasts that require manual
// dismissal interrupt the operator's attention during a critical alert when
// they need to be scanning the dashboard, not clicking dismiss buttons.

import { useEffect } from 'react';

interface Props {
  message: string;
  onDismiss: () => void;
  autoDismissMs?: number;
}

export default function ErrorToast({
  message,
  onDismiss,
  autoDismissMs = 4000,
}: Props) {
  useEffect(() => {
    const timerId = setTimeout(() => {
      onDismiss();
    }, autoDismissMs);

    // I clean up the timeout so if the parent unmounts before the timer fires
    // we do not call onDismiss on an unmounted component and trigger a warning.
    return () => {
      clearTimeout(timerId);
    };
  }, [autoDismissMs, onDismiss]);

  return (
    <div
      role="alert"
      className="fixed bottom-4 right-4 z-50 flex items-start gap-3 rounded-lg bg-critical-600 px-4 py-3 text-white shadow-lg max-w-sm"
    >
      <p className="flex-1 text-sm leading-snug">{message}</p>
      <button
        onClick={onDismiss}
        aria-label="Dismiss error"
        className="shrink-0 text-white/80 hover:text-white transition-colors text-lg leading-none"
      >
        x
      </button>
    </div>
  );
}
