'use client';

import { useState } from 'react';
import api from '@/lib/api';
import { errorInfo } from '@/lib/apiCode';
import { describeApiError } from '@/lib/apiError';
import { useApiResource } from '@/hooks/useApiResource';
import { serverNow } from '@/lib/serverClock';
import { DEFAULT_TOKEN_DAYS, MAX_LIVE_TOKENS, TOKEN_SCOPES, daysProblem, daysUntil, scopesFor, tokenState } from '@/lib/tokenScopes';
import Button from '@/components/ui/Button';
import ConfirmDialog from '@/components/ui/ConfirmDialog';
import ErrorNotice from '@/components/ui/ErrorNotice';
import { Input, Select } from '@/components/ui/Input';
import ProofDialog, { type Proof } from '@/components/ui/ProofDialog';
import { SkeletonRows } from '@/components/ui/Skeleton';
import { StatusShape } from '@/components/ui/StatusBadge';
import Time from '@/components/ui/Time';
import Section, { FormMessage } from './Section';
import { CheckIcon, CopyIcon } from '@/components/ui/icons';
import { lookup } from '@/lib/lookup';
import type { UserProfile } from './types';

interface TokenRow {
  id: string;
  name: string;
  scope: string;
  created_at: string;
  expires_at: string;
  // null until the token has been used. It moves on at most once a minute.
  last_used_at: string | null;
}

interface Created extends TokenRow {
  // the secret. It is in the answer that creates the token and nowhere else, so it is held here only until the dialog is closed.
  token: string;
}

// API tokens (docs/api-reference.md, "API tokens"). Making one needs a session and a fresh proof (the password and a code with
// two-step), so it goes through the same proof dialog as the other dangerous actions. The secret is shown once: it lives in this
// component's state for as long as the dialog is open and is set to null when it closes and it is never written to storage.
export default function TokensSection({ user }: { user: UserProfile }) {
  const { data, error: loadError, loading, retry } = useApiResource<TokenRow[]>('/tokens', { what: 'Your API tokens' });
  const scopes = scopesFor(user.role);
  const [name, setName] = useState('');
  const [scope, setScope] = useState<string>('read');
  const [days, setDays] = useState(String(DEFAULT_TOKEN_DAYS));
  const [nameError, setNameError] = useState('');
  const [daysError, setDaysError] = useState('');
  const [asking, setAsking] = useState(false);
  const [created, setCreated] = useState<Created | null>(null);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState('');
  const [toRevoke, setToRevoke] = useState<TokenRow | null>(null);
  const [revoking, setRevoking] = useState(false);
  const [ok, setOk] = useState('');
  const [error, setError] = useState('');
  const [reference, setReference] = useState<string | null>(null);
  const live = data?.filter((t) => Date.parse(t.expires_at) > serverNow()).length ?? 0;
  const full = live >= MAX_LIVE_TOKENS;
  const scopeSentence = lookup(Object.fromEntries(TOKEN_SCOPES.map((s) => [s.value, s.sentence])), scope);

  function start(e: React.FormEvent) {
    e.preventDefault();
    setOk('');
    setError('');
    const trimmed = name.trim();
    const nErr = !trimmed ? 'Give the token a name, so you can tell it apart later.' : trimmed.length > 60 ? 'Use 60 characters or fewer.' : /[\u0000-\u001f\u007f]/.test(trimmed) ? 'Use letters, numbers and spaces.' : '';
    const dErr = daysProblem(days) ?? '';
    setNameError(nErr);
    setDaysError(dErr);
    if (nErr || dErr) return;
    setAsking(true);
  }

  async function make(proof: Proof) {
    const { data: made } = await api.post<Created>('/tokens', { name: name.trim(), scope, expires_in_days: Number(days), ...proof });
    setCreated(made);
    setCopied(false);
    setCopyError('');
    setName('');
    setScope('read');
    setDays(String(DEFAULT_TOKEN_DAYS));
    retry();
  }

  async function copy() {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created.token);
      setCopied(true);
      setCopyError('');
    } catch {
      setCopied(false);
      setCopyError('It could not be copied. Select it and copy it by hand.');
    }
  }

  // closing the dialog throws the secret away: the page cannot show it again and neither can the API
  function closeSecret() {
    setCreated(null);
    setCopied(false);
    setCopyError('');
  }

  async function revoke() {
    if (!toRevoke) return;
    setRevoking(true);
    try {
      await api.delete(`/tokens/${toRevoke.id}`);
      setOk(`Revoked ${toRevoke.name}.`);
      setToRevoke(null);
      retry();
    } catch (err) {
      const status = (err as { response?: { status?: number } }).response?.status;
      setToRevoke(null);
      if (status === 404) {
        retry();
      } else {
        const info = errorInfo(err);
        setError(info.detail ?? describeApiError(err, 'The token'));
        setReference(info.requestId ?? null);
      }
    } finally {
      setRevoking(false);
    }
  }

  return (
    <Section id="tokens" title="API tokens" description="An API token lets a script or the command line tool use PHAEMOS without your password. It acts as you, with no more than the scope you give it.">
      <div className="max-w-2xl space-y-5">
        <form onSubmit={start} noValidate className="max-w-md space-y-4">
          <Input label="Name" hint="For example: nightly export script" required maxLength={60} value={name} onChange={(e) => { setName(e.target.value); setNameError(''); }} error={nameError || undefined} wrapperClassName="min-h-[124px]" />
          <div>
            <Select label="Scope" value={scope} onChange={(e) => setScope(e.target.value)}>
              {scopes.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </Select>
            <p className="mt-1 text-base text-surface-700 dark:text-surface-300">{scopeSentence}</p>
          </div>
          <Input label="Valid for (days)" hint="From 1 to 365. A token stops working when its time is up." inputMode="numeric" required value={days} onChange={(e) => { setDays(e.target.value); setDaysError(''); }} error={daysError || undefined} className="num w-32" wrapperClassName="min-h-[124px]" />
          <Button type="submit" disabled={full}>Make a token</Button>
          {full && <p className="text-base text-surface-800 dark:text-surface-200">You already have {MAX_LIVE_TOKENS} live tokens. Revoke one first.</p>}
        </form>

        <p className="text-base text-surface-700 dark:text-surface-300">Changing your password, changing two-step sign-in or signing out your other sessions revokes every API token you have made. A token cannot make, change or revoke anything about your account.</p>

        {loading && !data ? (
          <SkeletonRows rows={2} label="Loading your API tokens" />
        ) : loadError && !data ? (
          <ErrorNotice message={loadError} onRetry={retry} />
        ) : data && data.length === 0 ? (
          <p className="text-base text-surface-700 dark:text-surface-300">You have no API tokens.</p>
        ) : (
          <ul className="divide-y divide-surface-200 border-y border-surface-200 dark:divide-surface-800 dark:border-surface-800">
            {(data ?? []).map((t) => {
              const state = tokenState(t.expires_at, serverNow());
              const left = daysUntil(t.expires_at, serverNow());
              return (
                <li key={t.id} className="flex min-h-[56px] flex-wrap items-center justify-between gap-x-4 gap-y-2 py-3">
                  <div className="min-w-0">
                    <p className="text-base font-medium text-surface-900 dark:text-surface-50">
                      {t.name}
                      <span className="ml-2 font-normal text-surface-700 dark:text-surface-300">{lookup(Object.fromEntries(TOKEN_SCOPES.map((s) => [s.value, s.label])), t.scope) ?? t.scope}</span>
                    </p>
                    <p className="text-base text-surface-600 dark:text-surface-400">
                      Made <Time value={t.created_at} format="date" />. {t.last_used_at ? <>Last used <Time value={t.last_used_at} format="relative" />.</> : 'Never used.'}
                    </p>
                    <p className="flex items-center gap-2 text-base text-surface-800 dark:text-surface-200">
                      <span className={state === 'ok' ? 'text-success-800 dark:text-success-400' : state === 'soon' ? 'text-warning-800 dark:text-warning-400' : 'text-critical-800 dark:text-critical-300'}>
                        <StatusShape shape={state === 'ok' ? 'circle' : state === 'soon' ? 'triangle' : 'square'} />
                      </span>
                      <span>
                        {state === 'expired' ? 'Expired' : state === 'soon' ? `Expires in ${left} ${left === 1 ? 'day' : 'days'}. Make a new one before then.` : 'Expires'}{' '}
                        {state !== 'soon' && <Time value={t.expires_at} format="date" />}
                      </span>
                    </p>
                  </div>
                  <Button variant="secondary" size="small" onClick={() => { setOk(''); setError(''); setToRevoke(t); }} aria-label={`Revoke ${t.name}`}>Revoke</Button>
                </li>
              );
            })}
          </ul>
        )}
        <FormMessage ok={ok} error={error} requestId={reference} />
      </div>

      <ProofDialog
        open={asking}
        title="Make this API token?"
        confirmLabel="Make token"
        onCancel={() => setAsking(false)}
        run={make}
        onDone={() => setAsking(false)}
        returnTo="/profile#tokens"
      >
        <p>{name.trim()} will act as you with the {scope} scope for {days} {Number(days) === 1 ? 'day' : 'days'}. You are shown the secret once.</p>
      </ProofDialog>

      <ConfirmDialog open={created !== null} title="Your new API token" confirmLabel="I have copied it" cancelLabel="Close" destructive={false} onCancel={closeSecret} onConfirm={closeSecret}>
        {created && (
          <div className="space-y-3">
            <p className="font-medium text-surface-900 dark:text-surface-50">This is the only time it is shown. It cannot be shown again, by you or by us. If you lose it, revoke it and make a new one.</p>
            <Input label={`Secret for ${created.name}`} readOnly value={created.token} onFocus={(e) => e.currentTarget.select()} className="num" />
            <Button variant="secondary" onClick={copy} icon={copied ? <CheckIcon /> : <CopyIcon />}>{copied ? 'Copied' : 'Copy token'}</Button>
            <p role="status" className="text-base text-surface-800 dark:text-surface-200">{copied ? 'Copied to the clipboard.' : ''}</p>
            <p role="alert" className="text-base font-medium text-critical-800 empty:hidden dark:text-critical-300">{copyError}</p>
          </div>
        )}
      </ConfirmDialog>

      <ConfirmDialog open={toRevoke !== null} title="Revoke this token?" confirmLabel="Revoke" onCancel={() => setToRevoke(null)} onConfirm={revoke} pending={revoking}>
        <p>{toRevoke?.name} stops working at once. Anything that uses it will get a 401 until it is given a new one.</p>
      </ConfirmDialog>
    </Section>
  );
}
