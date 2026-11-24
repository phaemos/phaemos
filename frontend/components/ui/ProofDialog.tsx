'use client';

import { useState, type ReactNode } from 'react';
import { describeApiError } from '@/lib/apiError';
import { errorInfo } from '@/lib/apiCode';
import { routeProofError } from '@/lib/proofErrors';
import RequestRef from '@/components/ui/RequestRef';
import { lockedMessage } from '@/lib/signInErrors';
import { signInWithProviderAgain } from '@/lib/session';
import { useApiResource } from '@/hooks/useApiResource';
import Button from '@/components/ui/Button';
import ConfirmDialog from '@/components/ui/ConfirmDialog';
import { Input, PasswordInput } from '@/components/ui/Input';
import { hasPassword, providerName, type UserProfile } from '@/components/profile/types';

// the proof an action that can do damage asks for, in the shape the API reads it (the same fields as the profile page's actions)
export interface Proof {
  password?: string;
  code?: string;
}

interface Props {
  open: boolean;
  title: string;
  confirmLabel: string;
  // says what is about to happen
  children: ReactNode;
  onCancel: () => void;
  // sends the request with the proof added to it. It throws the API's error, which this dialog turns into a message beside the field
  run: (proof: Proof) => Promise<void>;
  onDone: () => void;
  // where a provider account comes back to after signing in with its provider again
  returnTo: string;
  // draws the confirm button as a dangerous action (red). Default false
  destructive?: boolean;
  // a sentence about what else the action does, shown above the proof fields (for example that every access token is revoked)
  note?: ReactNode;
}

// asks the person who is signed in to prove it is them again before an action that could be misused by a stolen session: the password
// and a current two-step code as well when that is on. A provider account has no password, so it proves it with a code or with a sign-in
// with its provider in the last 5 minutes (which the API's own message asks for). A wrong proof is answered with 400 and counts toward
// the account lock, so nothing here retries it and a 429 is shown plainly.
export default function ProofDialog({ open, title, confirmLabel, children, onCancel, run, onDone, returnTo, destructive = false, note }: Props) {
  const me = useApiResource<UserProfile>('/auth/me', { what: 'Your account', enabled: open });
  const user = me.data;
  const needsPassword = user ? hasPassword(user) : true;
  const needsCode = Boolean(user?.totp_enabled);
  const providerOnly = Boolean(user && !needsPassword && !needsCode);
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [codeError, setCodeError] = useState('');
  const [dialogError, setDialogError] = useState('');
  const [reference, setReference] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function confirm() {
    setPasswordError('');
    setCodeError('');
    setDialogError('');
    setReference(null);
    if (!user) return;
    let stop = false;
    if (needsPassword && !password) { setPasswordError('Enter your current password.'); stop = true; }
    if (needsCode && code.length !== 6) { setCodeError('Enter the 6 digits from your authenticator app.'); stop = true; }
    if (stop) return;
    setPending(true);
    try {
      const proof: Proof = {};
      if (needsPassword) proof.password = password;
      if (needsCode) proof.code = code;
      await run(proof);
      setPassword('');
      setCode('');
      onDone();
    } catch (err) {
      // what to do comes from the error's code. The sentence is only what is shown.
      const info = errorInfo(err);
      const asks = { password: needsPassword, code: needsCode };
      const fallback = describeApiError(err, 'The request');
      const handled = routeProofError(err, asks, { password: setPasswordError, code: setCodeError, dialog: setDialogError }, fallback);
      if (!handled) {
        // a refusal about the action itself (an account that owns machines, the last admin, 20 live tokens): said for the whole dialog
        setDialogError(info.detail ?? fallback);
        setReference(info.requestId ?? null);
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <ConfirmDialog open={open} title={title} confirmLabel={confirmLabel} destructive={destructive} onCancel={onCancel} onConfirm={confirm} pending={pending || me.loading}>
      <div className="space-y-3">{children}</div>
      {note && <p className="mt-3 text-base text-surface-800 dark:text-surface-200">{note}</p>}
      <p className="mt-3 text-base text-surface-700 dark:text-surface-300">This needs you to prove it is you again, in case someone else is using your session.</p>
      {me.error && !user && <p role="alert" className="mt-3 text-base font-medium text-critical-800 dark:text-critical-300">{me.error}</p>}
      {needsPassword && user && (
        <PasswordInput label="Current password" value={password} onChange={(e) => { setPassword(e.target.value); setPasswordError(''); }} error={passwordError || undefined} autoComplete="current-password" wrapperClassName="mt-4 min-h-[100px]" />
      )}
      {needsCode && (
        <Input label="Code from your authenticator app" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => { setCode(e.target.value.replace(/\D/g, '').slice(0, 6)); setCodeError(''); }} error={codeError || undefined} className="num w-40 tracking-widest" wrapperClassName="mt-4 min-h-[100px]" />
      )}
      {providerOnly && user && (
        <div className="mt-4 space-y-3">
          <p className="text-base text-surface-800 dark:text-surface-200">
            You sign in with {providerName(user.oauth_provider) || 'your provider'}. Sign in with it again (it takes a moment and brings you back here), then repeat this within 5 minutes.
          </p>
          <Button variant="secondary" onClick={() => signInWithProviderAgain(user.oauth_provider ?? '', returnTo)}>Sign in with {providerName(user.oauth_provider) || 'your provider'} again</Button>
        </div>
      )}
      <p role="alert" className="mt-4 text-base font-medium text-critical-800 empty:hidden dark:text-critical-300">{dialogError}</p>
      {dialogError && <RequestRef id={reference} />}
    </ConfirmDialog>
  );
}
