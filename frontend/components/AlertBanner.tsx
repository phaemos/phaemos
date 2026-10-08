'use client';

import Link from 'next/link';
import { useState } from 'react';
import type { Alert } from '@/types';
import TicketForm from './tickets/TicketForm';

interface Props {
  alert: Alert;
}

// a dot and a word for each severity, so the colour is never the only signal
const severityStyle: Record<string, { dot: string; text: string; label: string }> = {
  info: { dot: 'bg-primary-500', text: 'text-primary-700 dark:text-primary-300', label: 'Info' },
  warning: { dot: 'bg-warning-500', text: 'text-warning-700 dark:text-warning-400', label: 'Warning' },
  critical: { dot: 'bg-critical-500', text: 'text-critical-700 dark:text-critical-400', label: 'Critical' },
};

function since(iso: string): string {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  return hours < 24 ? `${hours} h ago` : `${Math.round(hours / 24)} d ago`;
}

export default function AlertBanner({ alert }: Props) {
  const [modalOpen, setModalOpen] = useState(false);
  const style = severityStyle[alert.severity ?? 'info'] ?? severityStyle.info;

  const prefill = {
    device_id: alert.device_id,
    title: `Alert: ${alert.message ?? alert.severity}`,
    description: `Severity: ${alert.severity}. Triggered at ${new Date(alert.triggered_at).toLocaleString('en-GB')}.`,
  };

  return (
    <>
      <div className="flex items-center gap-4 px-4 py-3 text-sm">
        <span className={`inline-flex w-20 shrink-0 items-center gap-1.5 text-xs font-semibold ${style.text}`}>
          <span className={`h-2 w-2 rounded-full ${style.dot}`} aria-hidden="true" />
          {style.label}
        </span>
        <span className="min-w-0 flex-1 text-surface-800 dark:text-surface-200">{alert.message}</span>
        <time dateTime={alert.triggered_at} className="hidden shrink-0 text-xs text-surface-500 sm:block">{since(alert.triggered_at)}</time>
        {alert.rule_id === null ? (
          // the anomaly model opens its own ticket with every alert it raises
          <Link href="/tickets" className="shrink-0 text-xs font-medium text-brand-600 hover:underline dark:text-brand-400">
            View ticket
          </Link>
        ) : (
          <button type="button" onClick={() => setModalOpen(true)} className="shrink-0 text-xs font-medium text-brand-600 hover:underline dark:text-brand-400">
            Create ticket
          </button>
        )}
      </div>

      {modalOpen && (
        // close on backdrop click so the operator can dismiss without submitting.
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={() => setModalOpen(false)}
          role="dialog"
          aria-modal="true"
        >
          <div
            className="w-full max-w-lg"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex justify-end mb-2">
              <button
                type="button"
                onClick={() => setModalOpen(false)}
                className="text-white/70 hover:text-white text-sm"
              >
                Close
              </button>
            </div>
            <TicketForm
              prefill={prefill}
              onSuccess={() => setModalOpen(false)}
            />
          </div>
        </div>
      )}
    </>
  );
}
