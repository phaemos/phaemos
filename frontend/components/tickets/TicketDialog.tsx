'use client';

import { useEffect, useId, useRef, type ReactNode } from 'react';
import Button from '@/components/ui/Button';

interface Props {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}

// a modal that holds a form. ConfirmDialog owns its own two buttons, so a form that submits itself needs this twin:
// the same native dialog, so Escape closes it, focus stays inside and the browser returns focus to the opener;
// the field marked data-autofocus takes focus first, so a person starts typing straight away.
export default function TicketDialog({ open, title, onClose, children }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      d.showModal();
      d.querySelector<HTMLElement>('[data-autofocus]')?.focus();
    }
    if (!open && d.open) d.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
      className="m-auto max-h-[calc(100%-2rem)] w-[calc(100%-2rem)] max-w-lg overflow-y-auto rounded-lg border border-surface-300 bg-surface-0 p-0 text-surface-900 backdrop:bg-surface-950/60 dark:border-surface-700 dark:bg-surface-900 dark:text-surface-50"
    >
      <div className="flex items-center justify-between gap-3 border-b border-surface-200 px-5 py-2 dark:border-surface-800">
        <h2 id={titleId} className="text-base font-semibold">{title}</h2>
        <Button variant="ghost" onClick={onClose}>Close</Button>
      </div>
      <div className="p-5">{open && children}</div>
    </dialog>
  );
}
