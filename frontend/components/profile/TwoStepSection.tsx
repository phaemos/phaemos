'use client';

import { useState } from 'react';
import api from '@/lib/api';
import { errorInfo } from '@/lib/apiCode';
import { describeApiError } from '@/lib/apiError';
import { lockedMessage } from '@/lib/signInErrors';
import { storeSession } from '@/lib/session';
import Button from '@/components/ui/Button';
import ConfirmDialog from '@/components/ui/ConfirmDialog';
import { TOKENS_REVOKED_NOTE } from '@/lib/tokenScopes';
import { Input, PasswordInput } from '@/components/ui/Input';
import Section, { FormMessage } from './Section';
import { hasPassword, providerName, type UserChange, type UserProfile } from './types';
import { signInWithProviderAgain } from '@/lib/session';

const BAD_CODE = 'That code did not work. Wait for the next one and try again.';

// /auth/2fa/enable takes {"password"} and returns a QR code and the secret. /2fa/confirm takes {"code"} and /2fa/disable takes
// {"code","password"}, both in the body. They answer with a fresh access token because they end every other session. A
// provider account has no password: turning two-step on needs a provider sign-in in the last 5 minutes (the API answers 400
// with the message otherwise) and turning it off needs only the code.
export default function TwoStepSection({ user, onChange }: { user: UserProfile; onChange: UserChange }) {
  const [setup, setSetup] = useState<{ qr: string; secret: string } | null>(null);
  const [code, setCode] = useState('');
  const [codeError, setCodeError] = useState('');
  const [error, setError] = useState('');
  const [ok, setOk] = useState('');
  const [reference, setReference] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [askOff, setAskOff] = useState(false);
  const [password, setPassword] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [needsProvider, setNeedsProvider] = useState(false);
  const withPassword = hasPassword(user);

  const digits = (v: string) => v.replace(/\D/g, '').slice(0, 6);

  async function start() {
    setError('');
    setReference(null);
    setOk('');
    setPasswordError('');
    setNeedsProvider(false);
    if (withPassword && !password) {
      setPasswordError('Enter your current password.');
      return;
    }
    setPending(true);
    try {
      const { data } = await api.post<{ qr_code: string; secret: string }>('/auth/2fa/enable', withPassword ? { password } : {});
      setSetup({ qr: data.qr_code, secret: data.secret });
      setPassword('');
      setCode('');
    } catch (err) {
      const info = errorInfo(err);
      const locked = lockedMessage(err);
      if (locked) setError(locked);
      else if (info.code === 'provider_proof_required') {
        // a provider account must sign in with its provider again first
        setError(info.detail ?? 'Sign in with your provider again, then try again.');
        setNeedsProvider(true);
      } else if (info.code === 'proof_required' || info.code === 'proof_wrong' || info.code === 'password_wrong') setPasswordError(info.detail ?? 'That password is wrong.');
      else {
        setError(info.detail ?? describeApiError(err, 'Two-step sign-in'));
        setReference(info.requestId ?? null);
      }
    } finally {
      setPending(false);
    }
  }

  async function confirm(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setCodeError('');
    if (code.length !== 6) {
      setCodeError('Enter the 6 digits from your app.');
      return;
    }
    setPending(true);
    try {
      const { data } = await api.post<{ access_token?: string }>('/auth/2fa/confirm', { code });
      if (data.access_token) storeSession(data.access_token);
      onChange({ totp_enabled: true });
      setSetup(null);
      setCode('');
      setOk('Two-step sign-in is on. Every other session was signed out.');
    } catch (err) {
      const info = errorInfo(err);
      const locked = lockedMessage(err);
      if (locked) setError(locked);
      else if (info.code === 'two_step_code_wrong' || info.code === 'code_required' || info.code === 'proof_wrong') setCodeError(BAD_CODE);
      else {
        setError(info.detail ?? describeApiError(err, 'Two-step sign-in'));
        setReference(info.requestId ?? null);
      }
    } finally {
      setPending(false);
    }
  }

  function askToTurnOff(e: React.FormEvent) {
    e.preventDefault();
    setCodeError('');
    setError('');
    if (code.length !== 6) {
      setCodeError('Enter the 6 digits from your app.');
      return;
    }
    setPasswordError('');
    if (withPassword && !password) {
      setPasswordError('Enter your current password to turn two-step sign-in off.');
      return;
    }
    setAskOff(true);
  }

  async function turnOff() {
    setPending(true);
    try {
      const { data } = await api.post<{ access_token?: string }>('/auth/2fa/disable', withPassword ? { code, password } : { code });
      if (data.access_token) storeSession(data.access_token);
      onChange({ totp_enabled: false });
      setCode('');
      setPassword('');
      setAskOff(false);
      setOk('Two-step sign-in is off.');
    } catch (err) {
      setAskOff(false);
      const info = errorInfo(err);
      const locked = lockedMessage(err);
      if (locked) setError(locked);
      else if (info.code === 'password_wrong' || info.code === 'proof_required') setPasswordError(info.detail ?? 'That password is wrong.');
      else if (info.code === 'two_step_code_wrong' || info.code === 'code_required' || info.code === 'proof_wrong') setCodeError(BAD_CODE);
      else {
        setError(info.detail ?? describeApiError(err, 'Two-step sign-in'));
        setReference(info.requestId ?? null);
      }
    } finally {
      setPending(false);
    }
  }

  const passwordInput = (label: string) => (
    <PasswordInput label={label} autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} error={passwordError || undefined} wrapperClassName="min-h-[100px]" />
  );

  const codeInput = (label: string) => (
    <Input
      label={label}
      hint="The 6 digits your authenticator app shows."
      inputMode="numeric"
      autoComplete="one-time-code"
      maxLength={6}
      required
      value={code}
      onChange={(e) => setCode(digits(e.target.value))}
      error={codeError || undefined}
      className="num w-40 tracking-widest"
      wrapperClassName="min-h-[124px]"
    />
  );

  return (
    <Section id="two-step" title="Two-step sign-in" description={user.totp_enabled ? 'On. We ask for a code from your authenticator app each time you sign in.' : 'Ask for a code from an authenticator app each time you sign in.'}>
      <div className="max-w-md space-y-4">
        {!user.totp_enabled && !setup && (
          <div className="space-y-4">
            {withPassword && passwordInput('Current password')}
            <Button onClick={start} pending={pending}>Turn on</Button>
            {needsProvider && (
              <Button
                variant="secondary"
                onClick={() => signInWithProviderAgain(user.oauth_provider ?? '', '/profile#two-step')}
              >
                Sign in with {providerName(user.oauth_provider) || 'your provider'} again
              </Button>
            )}
          </div>
        )}

        {!user.totp_enabled && setup && (
          <form onSubmit={confirm} noValidate className="space-y-4">
            <p className="text-base text-surface-700 dark:text-surface-300">Scan the code with your authenticator app, then type the 6 digits it shows. Turning two-step on signs out your other sessions. {TOKENS_REVOKED_NOTE}</p>
            {/* next/image does not support data: URIs, so a base64 QR code uses a plain img */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={`data:image/png;base64,${setup.qr}`} alt="QR code to scan with your authenticator app" width={192} height={192} className="h-48 w-48 rounded-md bg-white p-2" />
            <p className="text-base text-surface-700 dark:text-surface-300">
              Cannot scan it? Enter this key in the app instead: <code className="num break-all text-surface-900 dark:text-surface-50">{setup.secret}</code>
            </p>
            {codeInput('Code')}
            <div className="flex flex-wrap gap-3">
              <Button type="submit" pending={pending}>Confirm</Button>
              <Button variant="secondary" onClick={() => { setSetup(null); setCode(''); setCodeError(''); }}>Cancel</Button>
            </div>
          </form>
        )}

        {user.totp_enabled && (
          <form onSubmit={askToTurnOff} noValidate className="space-y-4">
            {withPassword && passwordInput('Current password')}
            {codeInput('Code to turn off')}
            <Button type="submit" variant="secondary">Turn off</Button>
          </form>
        )}

        <FormMessage ok={ok} error={error} requestId={reference} />
      </div>

      <ConfirmDialog open={askOff} title="Turn off two-step sign-in?" confirmLabel="Turn off" onCancel={() => setAskOff(false)} onConfirm={turnOff} pending={pending}>
        <p>Signing in will need only your password. Every other session is signed out. {TOKENS_REVOKED_NOTE}</p>
      </ConfirmDialog>
    </Section>
  );
}
