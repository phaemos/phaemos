'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import ConfirmDialog from '@/components/ui/ConfirmDialog';
import { clearSession } from '@/lib/session';

export default function LogoutButton({ variant = 'text', className = '' }: { variant?: 'text' | 'menu'; className?: string }) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);

  async function handleLogout() {
    if (pending) return;
    setPending(true);
    // the session is ended on the server first and the answer awaited, then this browser is cleared. Without the call the
    // refresh cookie would still sign the next person in.
    const reached = await clearSession();
    if (reached) {
      router.push('/login');
      return;
    }
    // the API did not answer, so the session may still be open. Say so and leave the choice to the person.
    setPending(false);
    setFailed(true);
  }

  async function leaveAnyway() {
    await clearSession({ anyway: true });
    setFailed(false);
    router.push('/login');
  }

  const label = pending ? 'Signing out' : 'Sign out';
  const dialog = (
    <ConfirmDialog
      open={failed}
      title="Could not sign you out"
      confirmLabel="Try again"
      cancelLabel="Stay signed in"
      destructive={false}
      onCancel={() => setFailed(false)}
      onConfirm={() => { setFailed(false); void handleLogout(); }}
    >
      <p>The server did not answer, so your session may still be open here and on other devices. Try again or sign out on this device only, which leaves the session open on the server until it expires.</p>
      <p className="mt-3">
        <button type="button" onClick={leaveAnyway} className="min-h-[44px] text-base text-brand-800 underline underline-offset-2 hover:no-underline dark:text-brand-400">Sign out on this device only</button>
      </p>
    </ConfirmDialog>
  );

  if (variant === 'menu') {
    return (
      <>
        <button
          type="button"
          role="menuitem"
          onClick={handleLogout}
          aria-disabled={pending}
          className={`flex w-full items-center rounded-md px-3 text-left text-base text-critical-800 hover:bg-surface-100 dark:text-critical-300 dark:hover:bg-surface-800 ${className}`}
        >
          {label}
        </button>
        {dialog}
      </>
    );
  }

  return (
    <>
      <button
        onClick={handleLogout}
        aria-disabled={pending}
        className={`text-base text-surface-600 hover:text-critical-800 dark:text-surface-400 dark:hover:text-critical-400 ${className}`}
      >
        {label}
      </button>
      {dialog}
    </>
  );
}
