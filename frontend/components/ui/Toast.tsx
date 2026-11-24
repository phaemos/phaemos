'use client';

import { useToast } from '@/hooks/useToast';

const _ICONS: Record<string, string> = {
  success: '✓',
  warning: '⚠',
  error: '✕',
  info: 'i',
};

const _STYLES: Record<string, string> = {
  success: 'bg-success-50 dark:bg-surface-900 border-success-500 text-success-800 dark:text-success-400',
  warning: 'bg-warning-50 dark:bg-surface-900 border-warning-500 text-warning-800 dark:text-warning-400',
  error:   'bg-critical-50 dark:bg-surface-900 border-critical-500 text-critical-800 dark:text-critical-300',
  info:    'bg-brand-50 dark:bg-surface-900 border-brand-500 text-brand-800 dark:text-brand-300',
};

export default function ToastContainer() {
  const { toasts, removeToast } = useToast();

  if (!toasts.length) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm w-full">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`flex items-start gap-3 px-4 py-3 rounded-lg border text-base

            ${_STYLES[toast.type] ?? _STYLES.info}`}
        >
          <span className="font-bold shrink-0 w-4 text-center">{_ICONS[toast.type]}</span>
          <span className="flex-1">{toast.message}</span>
          <button
            onClick={() => removeToast(toast.id)}
            className="shrink-0 opacity-60 hover:opacity-100 transition-opacity"
            aria-label="Dismiss"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
