'use client';

import { useIdempotencyKey } from '@/hooks/useIdempotencyKey';
import { idempotent } from '@/lib/idempotency';
import { useState } from 'react';
import api from '@/lib/api';
import { useApiResource } from '@/hooks/useApiResource';
import { roleWord } from '@/lib/format';
import { ACTION_LABELS, isActive, serviceActionsFor, type Person, type PersonAction } from '@/lib/people';
import { DEFAULT_TOKEN_DAYS, TOKEN_SCOPES, daysProblem, tokenState, daysUntil } from '@/lib/tokenScopes';
import { serverNow } from '@/lib/serverClock';
import { lookup } from '@/lib/lookup';
import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import ConfirmDialog from '@/components/ui/ConfirmDialog';
import ErrorNotice from '@/components/ui/ErrorNotice';
import { CheckIcon, CopyIcon } from '@/components/ui/icons';
import { Input, Select } from '@/components/ui/Input';
import Panel from '@/components/ui/Panel';
import ProofDialog, { type Proof } from '@/components/ui/ProofDialog';
import { SkeletonRows } from '@/components/ui/Skeleton';
import { StatusShape } from '@/components/ui/StatusBadge';
import Time from '@/components/ui/Time';

interface TokenRow {
  id: string;
  name: string;
  scope: string;
  created_at: string;
  expires_at: string;
  last_used_at: string | null;
}

interface Created extends TokenRow {
  // the secret, held only until its dialog is closed
  token: string;
}

type Acting = { kind: 'create-account' } | { kind: 'action'; action: PersonAction; account: Person } | { kind: 'make-token'; account: Person };

const SENTENCES: Readonly<Record<string, (p: Person) => string>> = {
  role: (p) => `Change what ${p.name ?? 'this service account'} may do.`,
  deactivate: (p) => `${p.name ?? 'This service account'} stops working and every API token it owns stops with it.`,
  reactivate: (p) => `${p.name ?? 'This service account'} works again.`,
  remove: (p) => `${p.name ?? 'This service account'} is removed with its API tokens. This cannot be undone.`,
};

// service accounts: an account for a script or an integration and not for a person, so that it keeps working when the person who set it up
// leaves. It has a role and owns API tokens and it cannot sign in by any route. An admin makes one (POST /service-accounts), changes its
// role, deactivates, reactivates and removes it through the /users routes and manages its API tokens (GET and POST /tokens with account_id,
// DELETE /tokens/{id}). Every one of those asks for the admin's fresh proof.
export default function ServiceAccounts({ accounts, people, onChanged }: { accounts: Person[]; people: Person[]; onChanged: () => void }) {
  const idem = useIdempotencyKey();
  const [open, setOpen] = useState<string | null>(null);
  const [acting, setActing] = useState<Acting | null>(null);
  const [name, setName] = useState('');
  const [nameError, setNameError] = useState('');
  const [role, setRole] = useState<Person['role']>('viewer');
  const [newRole, setNewRole] = useState<Person['role']>('viewer');
  const [notice, setNotice] = useState('');
  // the token form for the open account
  const [tokenName, setTokenName] = useState('');
  const [tokenScope, setTokenScope] = useState('read');
  const [tokenDays, setTokenDays] = useState(String(DEFAULT_TOKEN_DAYS));
  const [tokenErrors, setTokenErrors] = useState<{ name?: string; days?: string }>({});
  const [created, setCreated] = useState<Created | null>(null);
  const [copied, setCopied] = useState(false);
  const [toRevoke, setToRevoke] = useState<TokenRow | null>(null);
  const [revokeError, setRevokeError] = useState('');
  const tokens = useApiResource<TokenRow[]>(open ? '/tokens' : null, { params: { account_id: open ?? undefined }, what: 'Its API tokens', enabled: Boolean(open) });

  async function run(proof: Proof) {
    if (!acting) return;
    if (acting.kind === 'create-account') {
      // one Idempotency-Key for this submission, kept across a retry
      await api.post('/service-accounts', { name: name.trim(), role, ...proof }, idempotent(idem.keyFor(JSON.stringify({ name: name.trim(), role }))));
      idem.renew();
      setName('');
    } else if (acting.kind === 'make-token') {
      const { data } = await api.post<Created>('/tokens', { name: tokenName.trim(), scope: tokenScope, expires_in_days: Number(tokenDays), account_id: acting.account.id, ...proof });
      setCreated(data);
      setCopied(false);
      setTokenName('');
      tokens.retry();
    } else {
      const base = `/users/${acting.account.id}`;
      if (acting.action === 'role') await api.patch(`${base}/role`, { role: newRole, ...proof });
      else if (acting.action === 'remove') await api.delete(base, { data: proof });
      else await api.post(`${base}/${acting.action}`, proof);
    }
  }

  function done() {
    if (acting?.kind === 'create-account') setNotice('The service account is made. It cannot sign in. Make an API token for it below.');
    else if (acting?.kind === 'action') setNotice(acting.action === 'remove' ? 'The service account is removed.' : 'Done.');
    setActing(null);
    onChanged();
  }

  async function revoke() {
    if (!toRevoke) return;
    setRevokeError('');
    try {
      await api.delete(`/tokens/${toRevoke.id}`);
      setToRevoke(null);
      tokens.retry();
    } catch (err) {
      const status = (err as { response?: { status?: number } }).response?.status;
      if (status === 404) {
        setToRevoke(null);
        tokens.retry();
      } else setRevokeError('The API token could not be revoked. Try again.');
    }
  }

  function startToken(account: Person, e: React.FormEvent) {
    e.preventDefault();
    const nErr = !tokenName.trim() ? 'Give the API token a name.' : tokenName.trim().length > 60 ? 'Use 60 characters or fewer.' : '';
    const dErr = daysProblem(tokenDays) ?? '';
    setTokenErrors({ name: nErr || undefined, days: dErr || undefined });
    if (!nErr && !dErr) setActing({ kind: 'make-token', account });
  }

  return (
    <Panel title="Service accounts" description="An account for a script or an integration and not for a person, so that it keeps working when the person who set it up leaves. It has a role and owns API tokens. It cannot sign in.">
      <div className="space-y-5">
        <form
          onSubmit={(e) => { e.preventDefault(); setNameError(!name.trim() ? 'Give the service account a name.' : ''); if (name.trim()) { setNotice(''); setActing({ kind: 'create-account' }); } }}
          noValidate
          className="grid gap-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto] sm:items-start"
        >
          <Input label="Name" hint="For example: nightly export" maxLength={60} value={name} onChange={(e) => { setName(e.target.value); setNameError(''); }} error={nameError || undefined} wrapperClassName="min-h-[124px]" />
          <Select label="Role" value={role} onChange={(e) => setRole(e.target.value as Person['role'])}>
            <option value="viewer">Viewer</option>
            <option value="technician">Technician</option>
            <option value="admin">Admin</option>
          </Select>
          <div className="sm:pt-7"><Button type="submit">Make service account</Button></div>
        </form>
        <div role="status" className="text-base text-surface-900 empty:hidden dark:text-surface-50">{notice}</div>

        {accounts.length === 0 ? (
          <p className="text-base text-surface-700 dark:text-surface-300">There are no service accounts.</p>
        ) : (
          <ul className="divide-y divide-surface-200 border-y border-surface-200 dark:divide-surface-800 dark:border-surface-800">
            {accounts.map((a) => (
              <li key={a.id} className="space-y-3 py-3">
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                  <div className="min-w-0">
                    <p className="break-words text-base font-medium text-surface-900 dark:text-surface-50">
                      {a.name ?? 'Service account'}
                      <span className="ml-2"><Badge>Service account</Badge></span>
                      <span className="ml-2 font-normal text-surface-700 dark:text-surface-300">{roleWord(a.role)}</span>
                    </p>
                    <p className="inline-flex items-center gap-2 text-base text-surface-800 dark:text-surface-200">
                      <span className={isActive(a) ? 'text-success-800 dark:text-success-400' : 'text-surface-700 dark:text-surface-300'}><StatusShape shape={isActive(a) ? 'circle' : 'square'} /></span>
                      {isActive(a) ? 'Active' : 'Deactivated'}
                    </p>
                  </div>
                  <Button variant="secondary" size="small" aria-expanded={open === a.id} aria-label={`${open === a.id ? 'Hide' : 'Show'} actions for the service account ${a.name ?? ''}`} onClick={() => { setOpen(open === a.id ? null : a.id); setTokenErrors({}); }}>
                    {open === a.id ? 'Hide' : 'Manage'}
                  </Button>
                </div>
                {open === a.id && (
                  <div className="space-y-5 pl-0">
                    <ul className="grid gap-3 sm:grid-cols-2">
                      {serviceActionsFor(a, people).map((s) => (
                        <li key={s.action}>
                          <Button variant={s.action === 'remove' ? 'danger' : 'secondary'} size="small" disabled={!s.enabled} onClick={() => { setNotice(''); setNewRole(a.role === 'viewer' ? 'technician' : 'viewer'); setActing({ kind: 'action', action: s.action, account: a }); }}>
                            {lookup(ACTION_LABELS, s.action)}
                          </Button>
                          {s.reason && <p className="mt-1 max-w-[40ch] text-base text-surface-700 dark:text-surface-300">{s.reason}</p>}
                        </li>
                      ))}
                    </ul>

                    <div className="space-y-3">
                      <h3 className="text-base font-semibold text-surface-900 dark:text-surface-50">API tokens of this service account</h3>
                      {tokens.loading && !tokens.data ? (
                        <SkeletonRows rows={2} label="Loading its API tokens" />
                      ) : tokens.error && !tokens.data ? (
                        <ErrorNotice message={tokens.error} onRetry={tokens.retry} />
                      ) : (tokens.data ?? []).length === 0 ? (
                        <p className="text-base text-surface-700 dark:text-surface-300">It has no API tokens.</p>
                      ) : (
                        <ul className="divide-y divide-surface-200 dark:divide-surface-800">
                          {(tokens.data ?? []).map((t) => {
                            const st = tokenState(t.expires_at, serverNow());
                            const left = daysUntil(t.expires_at, serverNow());
                            return (
                              <li key={t.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-2">
                                <div className="min-w-0">
                                  <p className="text-base font-medium text-surface-900 dark:text-surface-50">{t.name} <span className="font-normal text-surface-700 dark:text-surface-300">{lookup(Object.fromEntries(TOKEN_SCOPES.map((x) => [x.value, x.label])), t.scope) ?? t.scope}</span></p>
                                  <p className="text-base text-surface-700 dark:text-surface-300">
                                    {t.last_used_at ? <>Last used <Time value={t.last_used_at} format="relative" />.</> : 'Never used.'}{' '}
                                    {st === 'expired' ? 'Expired.' : st === 'soon' ? `Expires in ${left} ${left === 1 ? 'day' : 'days'}.` : <>Expires <Time value={t.expires_at} format="date" />.</>}
                                  </p>
                                </div>
                                <Button variant="secondary" size="small" onClick={() => { setRevokeError(''); setToRevoke(t); }} aria-label={`Revoke ${t.name}`}>Revoke</Button>
                              </li>
                            );
                          })}
                        </ul>
                      )}
                      <form onSubmit={(e) => startToken(a, e)} noValidate className="grid gap-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-start">
                        <Input label="API token name" maxLength={60} value={tokenName} onChange={(e) => { setTokenName(e.target.value); setTokenErrors((x) => ({ ...x, name: undefined })); }} error={tokenErrors.name} wrapperClassName="min-h-[100px]" />
                        <Select label="Scope" value={tokenScope} onChange={(e) => setTokenScope(e.target.value)}>
                          {TOKEN_SCOPES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                        </Select>
                        <Input label="Days" inputMode="numeric" value={tokenDays} onChange={(e) => { setTokenDays(e.target.value); setTokenErrors((x) => ({ ...x, days: undefined })); }} error={tokenErrors.days} className="num" wrapperClassName="min-h-[100px]" />
                        <div className="sm:pt-7"><Button type="submit" variant="secondary">Make API token</Button></div>
                      </form>
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <ProofDialog
        open={acting !== null}
        title={acting?.kind === 'create-account' ? 'Make this service account?' : acting?.kind === 'make-token' ? 'Make this API token?' : acting ? `${lookup(ACTION_LABELS, acting.action)}: ${acting.account.name ?? 'service account'}` : ''}
        confirmLabel={acting?.kind === 'create-account' ? 'Make service account' : acting?.kind === 'make-token' ? 'Make API token' : acting ? (lookup(ACTION_LABELS, acting.action) ?? 'Confirm') : 'Confirm'}
        destructive={acting?.kind === 'action' && (acting.action === 'remove' || acting.action === 'deactivate')}
        onCancel={() => setActing(null)}
        run={run}
        onDone={done}
        returnTo="/admin"
      >
        {acting?.kind === 'create-account' && <p>{name.trim()} will be a service account with the {role} role. It cannot sign in. You make its API tokens next.</p>}
        {acting?.kind === 'make-token' && <p>{tokenName.trim()} will act as {acting.account.name ?? 'the service account'} with the {tokenScope} scope for {tokenDays} {Number(tokenDays) === 1 ? 'day' : 'days'}. You are shown the secret once.</p>}
        {acting?.kind === 'action' && <p>{lookup(SENTENCES, acting.action)?.(acting.account)}</p>}
        {acting?.kind === 'action' && acting.action === 'role' && (
          <Select label="New role" value={newRole} onChange={(e) => setNewRole(e.target.value as Person['role'])}>
            <option value="viewer">Viewer</option>
            <option value="technician">Technician</option>
            <option value="admin">Admin</option>
          </Select>
        )}
      </ProofDialog>

      <ConfirmDialog open={created !== null} title="The new API token" confirmLabel="I have copied it" cancelLabel="Close" destructive={false} onCancel={() => { setCreated(null); setCopied(false); }} onConfirm={() => { setCreated(null); setCopied(false); }}>
        {created && (
          <div className="space-y-3">
            <p className="font-medium text-surface-900 dark:text-surface-50">This is the only time it is shown. It cannot be shown again, by you or by us.</p>
            <Input label={`Secret for ${created.name}`} readOnly value={created.token} onFocus={(e) => e.currentTarget.select()} className="num" />
            <Button variant="secondary" icon={copied ? <CheckIcon /> : <CopyIcon />} onClick={async () => { try { await navigator.clipboard.writeText(created.token); setCopied(true); } catch { setCopied(false); } }}>{copied ? 'Copied' : 'Copy API token'}</Button>
          </div>
        )}
      </ConfirmDialog>

      <ConfirmDialog open={toRevoke !== null} title="Revoke this API token?" confirmLabel="Revoke" onCancel={() => setToRevoke(null)} onConfirm={revoke}>
        <p>{toRevoke?.name} stops working at once.</p>
        <p role="alert" className="mt-2 text-base font-medium text-critical-800 empty:hidden dark:text-critical-300">{revokeError}</p>
      </ConfirmDialog>
    </Panel>
  );
}
