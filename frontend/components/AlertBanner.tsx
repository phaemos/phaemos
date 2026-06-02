'use client';

import { useState } from 'react';
import type { Alert } from '@/types';
import TicketForm from './tickets/TicketForm';

interface Props {
  alert: Alert;
}

const severityStyle: Record<string, string> = {
  info: 'bg-blue-50 dark:bg-blue-950/50 border-blue-400 dark:border-blue-500 text-blue-700 dark:text-blue-300',
  warning: 'bg-yellow-50 dark:bg-yellow-950/50 border-yellow-400 dark:border-yellow-500 text-yellow-700 dark:text-yellow-300',
  critical: 'bg-red-50 dark:bg-red-950/50 border-red-400 dark:border-red-500 text-red-700 dark:text-red-300',
};

export default function AlertBanner({ alert }: Props) {
  const [modalOpen, setModalOpen] = useState(false);
  const style = severityStyle[alert.severity ?? 'info'];

  const prefill = {
    device_id: alert.device_id,
    title: `Alert: ${alert.message ?? alert.severity}`,
    description: `Severity: ${alert.severity}. Triggered at ${new Date(alert.triggered_at).toLocaleString('en-GB')}.`,
  };

  return (
    <>
      <div className={`border rounded-lg px-4 py-3 text-sm flex items-center gap-3 ${style}`}>
        <span className="font-semibold uppercase tracking-wide">{alert.severity}</span>
        <span className="flex-1">{alert.message}</span>
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className="shrink-0 px-2.5 py-1 rounded text-xs font-medium bg-white/30 dark:bg-black/20 hover:bg-white/50 dark:hover:bg-black/30 transition-colors"
        >
          Create Ticket
        </button>
      </div>

      {modalOpen && (
        // I close on backdrop click so the operator can dismiss without submitting.
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
