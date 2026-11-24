'use client';

import { useEffect, useId, useRef, type ReactNode } from 'react';
import Button from './Button';

interface Props {
  open: boolean;
  title: string;
  // say what will happen and whether it can be undone
  children: ReactNode;
  confirmLabel: string;
  // a recognisable mark beside the confirm word, for example a copy icon
  confirmIcon?: ReactNode;
  cancelLabel?: string;
  // asks to close without acting: Cancel, Escape and a click on the backdrop
  onCancel: () => void;
  onConfirm: () => void;
  // work after confirming: the button shows a spinner and ignores clicks
  pending?: boolean;
  // false makes the confirm button an ordinary primary button, for a change that is not destructive
  destructive?: boolean;
}

// built on the native dialog element, so the browser traps focus inside, makes the page behind inert, closes on
// escape and returns focus to the control that opened it. Cancel is first and takes focus, so a stray Enter never
// confirms a destructive action.
export default function ConfirmDialog({ open, title, children, confirmLabel, confirmIcon, cancelLabel = 'Cancel', onCancel, onConfirm, pending, destructive = true }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(e) => {
        // the state is the caller's, so stop the browser closing it and ask instead
        e.preventDefault();
        if (!pending) onCancel();
      }}
      onClick={(e) => {
        if (e.target === ref.current && !pending) onCancel();
      }}
      className="m-auto w-[calc(100%-2rem)] max-w-md rounded-lg border border-surface-300 bg-surface-0 p-0 text-surface-900 backdrop:bg-surface-950/60 dark:border-surface-700 dark:bg-surface-900 dark:text-surface-50"
    >
      <div className="space-y-4 p-5">
        <h2 id={titleId} className="text-base font-semibold">{title}</h2>
        <div className="text-base text-surface-700 dark:text-surface-300">{children}</div>
        <div className="flex flex-wrap justify-end gap-3 pt-2">
          <Button variant="secondary" onClick={onCancel} disabled={pending} autoFocus>{cancelLabel}</Button>
          <Button variant={destructive ? 'danger' : 'primary'} onClick={onConfirm} pending={pending} icon={confirmIcon}>{confirmLabel}</Button>
        </div>
      </div>
    </dialog>
  );
}
