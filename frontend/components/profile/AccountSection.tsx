'use client';

import { useState } from 'react';
import api from '@/lib/api';
import { apiDetail } from '@/lib/apiDetail';
import { describeApiError } from '@/lib/apiError';
import Button from '@/components/ui/Button';
import Section, { FormMessage } from './Section';
import { Input, PasswordInput } from '@/components/ui/Input';
import { roleWord } from '@/lib/format';
import { hasPassword, providerName, type UserChange, type UserProfile } from './types';
import { errorInfo } from '@/lib/apiCode';
import { routeProofError } from '@/lib/proofErrors';

// PATCH /auth/me. The API leaves out any field that is null, so each form sends only its own fields. Changing the email
// needs the current password and a current two-step code as well when two-step is on. A provider account cannot change it
// (the API answers 403), so it is shown and not offered.
export default function AccountSection({ user, onChange }: { user: UserProfile; onChange: UserChange }) {
  const [name, setName] = useState(user.name ?? '');
  const [email, setEmail] = useState(user.email);
  const [emailError, setEmailError] = useState('');
  const [currentPassword, setCurrentPassword] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [code, setCode] = useState('');
  const [codeError, setCodeError] = useState('');
  const canChangeEmail = hasPassword(user) && !user.oauth_provider;
  const emailChanged = canChangeEmail && email.trim() !== user.email;
  const [error, setError] = useState('');
  const [ok, setOk] = useState('');
  const [reference, setReference] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setReference(null);
    setOk('');
    setEmailError('');
    setPasswordError('');
    setCodeError('');
    if (canChangeEmail && !/^\S+@\S+\.\S+$/.test(email.trim())) {
      setEmailError('Enter a full email address.');
      return;
    }
    if (emailChanged && !currentPassword) {
      setPasswordError('Enter your current password to change your email.');
      return;
    }
    if (emailChanged && user.totp_enabled && code.length !== 6) {
      setCodeError('Enter the 6 digits from your authenticator app.');
      return;
    }
    setPending(true);
    try {
      // an empty name is sent as an empty name: the API keeps it, so clearing the field really clears it
      const body: Record<string, string> = { name: name.trim() };
      if (emailChanged) {
        body.email = email.trim();
        body.current_password = currentPassword;
        if (user.totp_enabled) body.code = code;
      }
      const { data } = await api.patch<UserProfile>('/auth/me', body);
      onChange(data);
      setCurrentPassword('');
      setCode('');
      // the API ends every other session when the sign-in address changes. It mails the old address unless that address was typed
      // in less than an hour ago and never confirmed and it does not say which happened, so the page does not claim a mail.
      setOk(emailChanged ? `Saved. Sign in with ${data.email} from now on. Every other session was signed out. If your old address was confirmed, we have emailed it.` : 'Saved.');
    } catch (err) {
      // what to do comes from the error's code: a proof goes beside its field, a taken address beside the email, anything else is said
      // under the form with the request reference
      const info = errorInfo(err);
      const handled = routeProofError(err, { password: true, code: Boolean(user.totp_enabled) }, { password: setPasswordError, code: setCodeError, dialog: setError }, 'That did not work.');
      if (!handled) {
        if (info.code === 'email_in_use' && info.detail) setEmailError(info.detail);
        else {
          setError(info.detail ?? describeApiError(err, 'Your changes'));
          setReference(info.requestId ?? null);
        }
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <Section id="account" title="Account" description={`Your role is ${roleWord(user.role)}.`}>
      <form onSubmit={save} noValidate className="max-w-md space-y-4">
        <Input label="Name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
        {canChangeEmail ? (
          <>
            <Input label="Email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} error={emailError || undefined} wrapperClassName="min-h-[100px]" />
            {emailChanged && (
              <PasswordInput label="Current password" hint="Needed to change your email." autoComplete="current-password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} error={passwordError || undefined} wrapperClassName="min-h-[124px]" />
            )}
            {emailChanged && user.totp_enabled && (
              <Input label="Code from your authenticator app" hint="Two-step sign-in is on, so a current code is needed as well." inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} error={codeError || undefined} className="num w-40 tracking-widest" wrapperClassName="min-h-[124px]" />
            )}
          </>
        ) : (
          <div>
            <p className="text-base font-medium text-surface-900 dark:text-surface-50">Email</p>
            <p className="mt-1 text-base text-surface-900 dark:text-surface-50">{user.email}</p>
            <p className="mt-1 text-base text-surface-600 dark:text-surface-400">Your email comes from {providerName(user.oauth_provider) || 'your provider'} and cannot be changed here.</p>
          </div>
        )}
        <Button type="submit" pending={pending}>Save changes</Button>
        <FormMessage ok={ok} error={error} requestId={reference} />
      </form>
    </Section>
  );
}
