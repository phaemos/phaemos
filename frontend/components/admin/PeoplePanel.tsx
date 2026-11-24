'use client';

import { Fragment, useState } from 'react';
import api from '@/lib/api';
import { useApiResource } from '@/hooks/useApiResource';
import { roleWord } from '@/lib/format';
import { ACTION_LABELS, actionsFor, isActive, isService, type Person, type PersonAction } from '@/lib/people';
import { lookup } from '@/lib/lookup';
import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import DataTable from '@/components/ui/DataTable';
import EmptyState from '@/components/ui/EmptyState';
import ErrorNotice from '@/components/ui/ErrorNotice';
import { Select } from '@/components/ui/Input';
import Panel from '@/components/ui/Panel';
import ProofDialog, { type Proof } from '@/components/ui/ProofDialog';
import { SkeletonRows } from '@/components/ui/Skeleton';
import { StatusShape } from '@/components/ui/StatusBadge';
import Time from '@/components/ui/Time';
import InviteForm from './InviteForm';
import Invitations from './Invitations';
import ServiceAccounts from './ServiceAccounts';
import { useAllUsers } from './useAllUsers';
import { TOKENS_REVOKED_NOTE } from '@/lib/tokenScopes';

interface Acting {
  action: PersonAction;
  person: Person;
}

// what each action says before it is confirmed. Every one goes through the proof dialog (the admin's password and a code with two-step).
const SENTENCES: Readonly<Record<PersonAction, (p: Person) => string>> = {
  role: (p) => `Change what ${p.email} may do.`,
  deactivate: (p) => `${p.email} will not be able to sign in, refresh a session, reset a password or accept an invitation. Every session they have ends at once.`,
  reactivate: (p) => `${p.email} will be able to sign in again.`,
  'clear-two-step': (p) => `Two-step sign-in is switched off for ${p.email} and every session they have ends. They sign in with their password and can turn it on again. Use this for a lost authenticator.`,
  'reset-link': (p) => `We email a one-time link to choose a new password to ${p.email}, their own address. The link is never shown to you. It works once and lasts 2 hours. Using it ends every session they have.`,
  remove: (p) => `${p.email} is removed. Their tickets stay with their name taken off, their sessions go and the audit trail is kept. This cannot be undone.`,
};

const DONE: Readonly<Record<PersonAction, string>> = {
  role: 'The role is changed.',
  deactivate: 'The account is deactivated.',
  reactivate: 'The account is active again.',
  'clear-two-step': 'Two-step sign-in is cleared.',
  'reset-link': 'A reset link was emailed to their own address.',
  remove: 'The account is removed.',
};

// people (admins only): who can sign in, what each person may do and the work that touches an account. The list is GET /users, which
// now carries is_active, last_login and session_count. An admin cannot act on their own account (403) or leave the product with no active
// admin (409): those controls are off, with the reason written next to them and a refusal is still handled if it comes.
export default function PeoplePanel() {
  const users = useAllUsers();
  const me = useApiResource<{ id: string }>('/auth/me', { what: 'Your account' });
  const invitations = useApiResource<unknown[]>('/invitations', { what: 'The invitations' });
  const [open, setOpen] = useState<string | null>(null);
  const [acting, setActing] = useState<Acting | null>(null);
  const [role, setRole] = useState<Person['role']>('viewer');
  const [notice, setNotice] = useState('');

  const everyone = users.users as Person[];
  // service accounts are their own kind and have their own area below. A person's list holds people only.
  const people = everyone.filter((p) => !isService(p));
  const services = everyone.filter(isService);
  const loading = everyone.length === 0 && !users.error && !me.error;

  async function run(proof: Proof) {
    if (!acting) return;
    const base = `/users/${acting.person.id}`;
    switch (acting.action) {
      case 'role':
        await api.patch(`${base}/role`, { role, ...proof });
        break;
      case 'remove':
        await api.delete(base, { data: proof });
        break;
      default:
        await api.post(`${base}/${acting.action}`, proof);
    }
  }

  function done() {
    if (acting) setNotice(`${lookup(DONE, acting.action) ?? 'Done.'}`);
    setActing(null);
    setOpen(null);
    users.retry();
  }

  function start(action: PersonAction, person: Person) {
    setNotice('');
    setRole(action === 'role' ? (person.role === 'viewer' ? 'technician' : 'viewer') : role);
    setActing({ action, person });
  }

  const actionsPanel = (p: Person, where: 'table' | 'list') => (
    <div className="space-y-3 py-2">
      <ul className="grid gap-3 sm:grid-cols-2">
        {actionsFor(p, me.data?.id, everyone).map((a) => (
          <li key={a.action}>
            <Button variant={a.action === 'remove' ? 'danger' : 'secondary'} size="small" disabled={!a.enabled} aria-describedby={a.reason ? `why-${where}-${p.id}-${a.action}` : undefined} onClick={() => start(a.action, p)}>
              {lookup(ACTION_LABELS, a.action)}
            </Button>
            {a.reason && <p id={`why-${where}-${p.id}-${a.action}`} className="mt-1 max-w-[40ch] text-base text-surface-700 dark:text-surface-300">{a.reason}</p>}
          </li>
        ))}
      </ul>
    </div>
  );

  const state = (p: Person) => (
    <span className="inline-flex items-center gap-2">
      <span className={isActive(p) ? 'text-success-800 dark:text-success-400' : 'text-surface-700 dark:text-surface-300'}>
        <StatusShape shape={isActive(p) ? 'circle' : 'square'} />
      </span>
      {isActive(p) ? 'Active' : 'Deactivated'}
    </span>
  );

  // the table and the list are both in the page (one is hidden by the screen width), so each has its own ids
  const manage = (p: Person, where: 'table' | 'list') => (
    <Button variant="secondary" size="small" aria-expanded={open === p.id} aria-controls={`actions-${where}-${p.id}`} onClick={() => setOpen(open === p.id ? null : p.id)} aria-label={`${open === p.id ? 'Hide' : 'Show'} actions for ${p.email}`}>
      {open === p.id ? 'Hide' : 'Manage'}
    </Button>
  );

  return (
    <div className="space-y-6">
      <InviteForm onInvited={() => { users.retry(); invitations.retry(); }} />
      <Invitations resource={invitations} />

      <Panel title="People" bodyClassName="p-0">
        <div role="status" className="px-4 pt-3 text-base text-surface-900 empty:hidden dark:text-surface-50">{notice}</div>
        {loading ? (
          <div className="p-4"><SkeletonRows rows={4} label="Loading people" /></div>
        ) : users.error && everyone.length === 0 ? (
          <div className="p-4"><ErrorNotice message={users.error} onRetry={users.retry} /></div>
        ) : people.length === 0 ? (
          <EmptyState heading="No people yet" subMessage="Invite someone above and they appear here once they accept." />
        ) : (
          <>
            {users.error && <div className="p-4"><ErrorNotice message={users.error} onRetry={users.retry} /></div>}
            {/* a table on wide screens */}
            <div className="hidden lg:block">
              <DataTable caption="People">
                <thead>
                  <tr>
                    <th scope="col">Person</th>
                    <th scope="col">Role</th>
                    <th scope="col">State</th>
                    <th scope="col">Two-step</th>
                    <th scope="col">Last signed in</th>
                    <th scope="col">Sessions</th>
                    <th scope="col"><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {people.map((p) => (
                    <Fragment key={p.id}>
                      <tr>
                        <th scope="row" className="font-normal">
                          <span className="block text-surface-900 dark:text-surface-50">{p.name || <span className="text-surface-600 dark:text-surface-400">No name</span>}</span>
                          <span className="block text-surface-700 dark:text-surface-300">{p.email}</span>
                        </th>
                        <td><Badge>{roleWord(p.role)}</Badge></td>
                        <td>{state(p)}</td>
                        <td>{p.totp_enabled ? 'On' : 'Off'}</td>
                        <td>{p.last_login ? <Time value={p.last_login} format="relative" /> : <span className="text-surface-600 dark:text-surface-400">Never</span>}</td>
                        <td className="num">{p.session_count ?? ''}</td>
                        <td>{manage(p, 'table')}</td>
                      </tr>
                      {open === p.id && (
                        <tr id={`actions-table-${p.id}`}>
                          <td colSpan={7}>{actionsPanel(p, 'table')}</td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </DataTable>
            </div>
            {/* a list on narrow ones */}
            <ul className="divide-y divide-surface-200 lg:hidden dark:divide-surface-800">
              {people.map((p) => (
                <li key={p.id} className="space-y-2 px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="break-words text-base font-medium text-surface-900 dark:text-surface-50">{p.name || 'No name'}</p>
                      <p className="break-all text-base text-surface-700 dark:text-surface-300">{p.email}</p>
                    </div>
                    <Badge>{roleWord(p.role)}</Badge>
                  </div>
                  <p className="text-base text-surface-800 dark:text-surface-200">{state(p)}. Two-step {p.totp_enabled ? 'on' : 'off'}.</p>
                  <p className="text-base text-surface-700 dark:text-surface-300">
                    {p.last_login ? <>Last signed in <Time value={p.last_login} format="relative" />.</> : 'Never signed in.'} {typeof p.session_count === 'number' ? `${p.session_count} ${p.session_count === 1 ? 'session' : 'sessions'}.` : ''}
                  </p>
                  {manage(p, 'list')}
                  {open === p.id && <div id={`actions-list-${p.id}`}>{actionsPanel(p, 'list')}</div>}
                </li>
              ))}
            </ul>
          </>
        )}
      </Panel>

      <ServiceAccounts accounts={services} people={everyone} onChanged={users.retry} />

      <ProofDialog
        open={acting !== null}
        title={acting ? `${lookup(ACTION_LABELS, acting.action)}: ${acting.person.email}` : ''}
        confirmLabel={acting ? (lookup(ACTION_LABELS, acting.action) ?? 'Confirm') : 'Confirm'}
        destructive={acting?.action === 'remove' || acting?.action === 'deactivate'}
        onCancel={() => setActing(null)}
        run={run}
        onDone={done}
        returnTo="/admin"
      >
        {acting && <p>{lookup(SENTENCES, acting.action)?.(acting.person)}</p>}
        {acting?.action === 'role' && (
          <Select label="New role" value={role} onChange={(e) => setRole(e.target.value as Person['role'])}>
            <option value="viewer">Viewer</option>
            <option value="technician">Technician</option>
            <option value="admin">Admin</option>
          </Select>
        )}
        {acting && ['deactivate', 'clear-two-step', 'remove'].includes(acting.action) && <p>{TOKENS_REVOKED_NOTE}</p>}
      </ProofDialog>
    </div>
  );
}
