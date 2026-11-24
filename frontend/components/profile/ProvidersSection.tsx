'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';
import { apiDetail } from '@/lib/apiDetail';
import { describeApiError } from '@/lib/apiError';
import { linkMessage, withoutLinkParams } from '@/lib/linkResult';
import { parseProviders } from '@/lib/providers';
import { leaveFor, NOT_RECOGNISED } from '@/lib/session';
import Button from '@/components/ui/Button';
import ConfirmDialog from '@/components/ui/ConfirmDialog';
import { Input, PasswordInput } from '@/components/ui/Input';
import Section from './Section';
import { errorInfo } from '@/lib/apiCode';
import { routeProofError } from '@/lib/proofErrors';
import RequestRef from '@/components/ui/RequestRef';
import { providerName, type UserProfile } from './types';

const AUTH_API = `${process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'}/api/v1/auth`;

// the providers this installation signs people in with come from GET /auth/providers, so one that is not set up is not listed;
// a password account can link Google or GitHub (never Microsoft, whose addresses are not verified): POST /auth/link/{provider}
// with the proof (the password and a code when two-step is on) answers { authorize_url } and sets the state cookies and the
// browser then goes to that address. The callback returns to /profile?linked=<provider> or /profile?link_error=<code>, which
// this section reads, says in words and takes out of the address.
const LINKABLE = ['google', 'github'];

export default function ProvidersSection({ user }: { user: UserProfile }) {
  // null while the list is loading or if it could not be read: nothing is claimed about providers meanwhile
  const [available, setAvailable] = useState<string[] | null>(null);
  const [linking, setLinking] = useState<string | null>(null);
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [codeError, setCodeError] = useState('');
  const [dialogError, setDialogError] = useState('');
  const [reference, setReference] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    let alive = true;
    fetch(`${AUTH_API}/providers`, { credentials: 'omit' })
      .then((res) => (res.ok ? res.json() : null))
      .then((body) => { if (alive) setAvailable(body ? parseProviders(body) : null); })
      .catch(() => { if (alive) setAvailable(null); });
    return () => { alive = false; };
  }, []);

  // the return from a provider says how it went in the address. It is said once and then removed.
  useEffect(() => {
    const message = linkMessage(window.location.search);
    if (!message) return;
    // reading the address is synchronising with an external system
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setResult(message);
    window.history.replaceState(null, '', `${window.location.pathname}${withoutLinkParams(window.location.search)}${window.location.hash}`);
  }, []);

  const connected = user.oauth_provider;
  const hasPassword = user.has_password ?? !connected;
  const keys = [...new Set([...(available ?? []), ...(connected ? [connected] : [])])];
  const canLink = hasPassword && !connected;

  async function link() {
    if (!linking) return;
    setPasswordError('');
    setCodeError('');
    setDialogError('');
    setReference(null);
    let stop = false;
    if (!password) { setPasswordError('Enter your current password.'); stop = true; }
    if (user.totp_enabled && code.length !== 6) { setCodeError('Enter the 6 digits from your authenticator app.'); stop = true; }
    if (stop) return;
    setPending(true);
    try {
      const body: Record<string, string> = { password };
      if (user.totp_enabled) body.code = code;
      const { data } = await api.post<{ authorize_url?: string }>(`/auth/link/${linking}`, body);
      if (!data.authorize_url) throw new Error('no address');
      leaveFor(data.authorize_url, available ?? []);
    } catch (err) {
      setPending(false);
      const info = errorInfo(err);
      if (err instanceof Error && err.message === NOT_RECOGNISED) {
        setDialogError('The provider address the server gave was not one we recognise, so nothing was opened. Try again later or write to support.');
      } else if (!routeProofError(err, { password: true, code: Boolean(user.totp_enabled) }, { password: setPasswordError, code: setCodeError, dialog: setDialogError }, 'That did not work.')) {
        setDialogError(info.detail ?? describeApiError(err, 'The link'));
        setReference(info.requestId ?? null);
      }
    }
  }

  return (
    <Section id="providers" title="Sign-in providers" description={connected ? `You sign in with ${providerName(connected)}${hasPassword ? ' or with your password' : ''}.` : 'You sign in with an email address and a password.'}>
      {keys.length > 0 && (
        <ul className="max-w-md divide-y divide-surface-200 border-y border-surface-200 dark:divide-surface-800 dark:border-surface-800">
          {keys.map((key) => (
            <li key={key} className="flex min-h-[56px] items-center justify-between gap-3 py-2">
              <span className="text-base text-surface-900 dark:text-surface-50">
                {providerName(key)}
                <span className="ml-2 text-surface-600 dark:text-surface-400">{connected === key ? 'Connected' : 'Not connected'}</span>
              </span>
              {canLink && LINKABLE.includes(key) && (
                <Button variant="secondary" size="small" aria-label={`Connect ${providerName(key)}`} onClick={() => { setPassword(''); setCode(''); setPasswordError(''); setCodeError(''); setDialogError(''); setLinking(key); }}>
                  Connect
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 max-w-[72ch] text-base text-surface-700 dark:text-surface-300">
        {!hasPassword
          ? 'This account has no password. Its email address comes from the provider.'
          : connected
            ? 'Your email address is the same at the provider and here.'
            : available !== null && available.length === 0
              ? 'No sign-in provider is set up on this installation.'
              : canLink && keys.some((k) => LINKABLE.includes(k))
              ? 'A provider can be linked when its email address is the one on this account. You prove it is you first.'
              : 'No provider can be linked to this account here.'}
      </p>
      <div role={result?.ok === false ? 'alert' : 'status'} className="mt-2 min-h-5 text-base text-surface-900 dark:text-surface-50">{result?.text}</div>
      <ConfirmDialog open={linking !== null} title={`Connect ${providerName(linking)}?`} confirmLabel="Continue" destructive={false} onCancel={() => setLinking(null)} onConfirm={link} pending={pending}>
        <p>You go to {linking ? providerName(linking) : 'the provider'} to confirm, then come back here. Its email address has to be {user.email}.</p>
        <PasswordInput label="Current password" value={password} onChange={(e) => { setPassword(e.target.value); setPasswordError(''); }} error={passwordError || undefined} autoComplete="current-password" wrapperClassName="mt-4 min-h-[100px]" />
        {user.totp_enabled && (
          <Input label="Code from your authenticator app" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => { setCode(e.target.value.replace(/\D/g, '').slice(0, 6)); setCodeError(''); }} error={codeError || undefined} className="num w-40 tracking-widest" wrapperClassName="mt-4 min-h-[100px]" />
        )}
        <p role="alert" className="mt-4 text-base font-medium text-critical-800 empty:hidden dark:text-critical-300">{dialogError}</p>
        {dialogError && <RequestRef id={reference} />}
      </ConfirmDialog>
    </Section>
  );
}
