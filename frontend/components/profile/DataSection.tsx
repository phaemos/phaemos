'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import api from '@/lib/api';
import { describeApiError } from '@/lib/apiError';
import { errorInfo } from '@/lib/apiCode';
import { routeProofError } from '@/lib/proofErrors';
import { clearSession, signInWithProviderAgain } from '@/lib/session';
import Button from '@/components/ui/Button';
import ConfirmDialog from '@/components/ui/ConfirmDialog';
import { Input, PasswordInput } from '@/components/ui/Input';
import Section, { FormMessage } from './Section';
import TextLink from '@/components/content/TextLink';
import { isSplit, siteHref } from '@/lib/links';
import { hasPassword, providerName, type UserProfile } from './types';

const FILE_NAME = 'phaemos-data-export.json';

// GET /auth/me/export needs the Authorization header, which a plain link cannot send. The request goes through
// lib/api.ts like every other call, so the session is sent in the header and never in the address, then the answer
// is handed to the browser as a file.
export function ExportSection() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [ok, setOk] = useState('');

  async function download() {
    setError('');
    setOk('');
    setPending(true);
    try {
      const res = await api.get<Blob>('/auth/me/export', { responseType: 'blob' });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement('a');
      a.href = url;
      a.download = FILE_NAME;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setOk(`Downloaded ${FILE_NAME}.`);
    } catch (err) {
      setError(describeApiError(err, 'The export'));
    } finally {
      setPending(false);
    }
  }

  return (
    <Section id="export" title="Download your data" description="A JSON file with your profile, the machines you own, the tickets you raised or were assigned, the maintenance windows you created, your API tokens (their names, scopes and dates, never the secrets) and your own entries in the log of changes.">
      <div className="space-y-4">
        <Button variant="secondary" onClick={download} pending={pending}>Download my data</Button>
        <FormMessage ok={ok} error={error} />
        <p className="max-w-[72ch] text-base text-surface-700 dark:text-surface-300">
          What we keep, why and for how long is in the <TextLink href={siteHref('/privacy')}>privacy notice</TextLink>.
        </p>
      </div>
    </Section>
  );
}

// DELETE /auth/me needs proof in its body, chosen from /auth/me:
//   a password account sends the password and a current two-step code as well when two-step is on
//   a provider account with two-step sends a current code
//   a provider account with neither sends no field, but must have returned from its provider in the last 5 minutes, so the
//   page sends the person through the provider and back here first
// the API answers 400 with the message to show when a proof is missing or wrong. The password message and the code message
// are different, so each shows beside its own field. It answers 409 when the person owns machines or is the last admin and
// 429 once the account is locked by wrong proofs.
export type Proof = 'password' | 'password-and-code' | 'code' | 'provider';

export function proofFor(user: UserProfile): Proof {
  if (hasPassword(user)) return user.totp_enabled ? 'password-and-code' : 'password';
  return user.totp_enabled ? 'code' : 'provider';
}

export function DeleteSection({ user }: { user: UserProfile }) {
  const router = useRouter();
  const proof = proofFor(user);
  const needsPassword = proof === 'password' || proof === 'password-and-code';
  const needsCode = proof === 'code' || proof === 'password-and-code';
  const provider = providerName(user.oauth_provider) || 'your provider';
  const recent = Boolean(user.provider_signin_recent);
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [codeError, setCodeError] = useState('');
  const [dialogError, setDialogError] = useState('');
  const [error, setError] = useState('');
  const [reference, setReference] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  // the provider form: there is nothing to type, so the first press sends the person to their provider and the second,
  // after they come back, asks for the final confirmation
  function startProvider() {
    signInWithProviderAgain(user.oauth_provider ?? '', '/profile#delete');
  }

  async function remove() {
    setPasswordError('');
    setCodeError('');
    setDialogError('');
    let stop = false;
    if (needsPassword && !password) {
      setPasswordError('Enter your current password.');
      stop = true;
    }
    if (needsCode && code.length !== 6) {
      setCodeError('Enter the 6 digits from your authenticator app.');
      stop = true;
    }
    if (stop) return;
    setPending(true);
    try {
      const body: Record<string, string> = {};
      if (needsPassword) body.password = password;
      if (needsCode) body.code = code;
      await api.delete('/auth/me', { data: body });
      // the API clears the refresh cookie. The sign-out call is still made, as the reference asks, then this browser forgets the session.
      await clearSession({ anyway: true });
      // the account is gone, so leave the dashboard for the public home page, which is another address when split. The home
      // page says that the account was deleted.
      const home = '/?account=deleted';
      if (isSplit) window.location.assign(siteHref(home));
      else router.replace(home);
    } catch (err) {
      setPending(false);
      // a wrong or missing proof (by code) stays in the dialog so it can be tried again and a 429 is said there in plain words
      if (routeProofError(err, { password: needsPassword, code: needsCode }, { password: setPasswordError, code: setCodeError, dialog: setDialogError }, 'That did not work.')) return;
      const info = errorInfo(err);
      setOpen(false);
      setError(info.detail ?? describeApiError(err, 'The account'));
      setReference(info.requestId ?? null);
    }
  }

  return (
    <Section id="delete" title="Delete your account" description="Deletes your account and takes your name off the tickets you raised. This cannot be undone.">
      <div className="max-w-md space-y-4">
        {proof === 'provider' && !recent ? (
          <>
            <p className="text-base text-surface-700 dark:text-surface-300">
              To delete this account, sign in with {provider} again first. You come back to this page and have 5 minutes to finish.
            </p>
            <Button variant="secondary" onClick={startProvider}>Sign in with {provider} again</Button>
          </>
        ) : (
          <>
            {proof === 'provider' && (
              <p className="text-base text-surface-700 dark:text-surface-300">You signed in with {provider} a moment ago, so you can delete the account now. This works for 5 minutes.</p>
            )}
            <Button variant="danger" onClick={() => { setPassword(''); setCode(''); setPasswordError(''); setCodeError(''); setDialogError(''); setError(''); setOpen(true); }}>Delete my account</Button>
          </>
        )}
        <FormMessage error={error} requestId={reference} />
        <p className="text-base text-surface-600 dark:text-surface-400">
          An account cannot be deleted while it owns machines or is the last admin. An admin hands the machines on or makes another admin first. If that is not possible, write to <TextLink href="mailto:support@phaemos.com">support@phaemos.com</TextLink>.
        </p>
      </div>
      <ConfirmDialog open={open} title="Delete your account?" confirmLabel="Delete account" onCancel={() => setOpen(false)} onConfirm={remove} pending={pending}>
        <p>This deletes the account and signs you out. Tickets you raised stay, without your name on them.</p>
        {needsPassword && (
          <PasswordInput
            label="Current password"
            value={password}
            onChange={(e) => { setPassword(e.target.value); setPasswordError(''); }}
            error={passwordError || undefined}
            autoComplete="current-password"
            wrapperClassName="mt-4 min-h-[100px]"
          />
        )}
        {needsCode && (
          <Input
            label="Code from your authenticator app"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            value={code}
            onChange={(e) => { setCode(e.target.value.replace(/\D/g, '').slice(0, 6)); setCodeError(''); }}
            error={codeError || undefined}
            className="num w-40 tracking-widest"
            wrapperClassName="mt-4 min-h-[100px]"
          />
        )}
        <p role="alert" className="mt-4 text-base font-medium text-critical-800 empty:hidden dark:text-critical-300">{dialogError}</p>
      </ConfirmDialog>
    </Section>
  );
}
