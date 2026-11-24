'use client';

import { useState } from 'react';
import api from '@/lib/api';
import { errorInfo } from '@/lib/apiCode';
import RequestRef from '@/components/ui/RequestRef';
import { describeApiError } from '@/lib/apiError';
import Button from '@/components/ui/Button';
import { CheckIcon, CopyIcon } from '@/components/ui/icons';
import { Input, Select } from '@/components/ui/Input';
import Panel from '@/components/ui/Panel';
import ProofDialog, { type Proof } from '@/components/ui/ProofDialog';
import { useIdempotencyKey } from '@/hooks/useIdempotencyKey';
import { idempotent } from '@/lib/idempotency';

interface InviteResult {
  email: string;
  email_sent: boolean;
  invite_link: string;
}

// inviting an admin hands over the keys to everything, so it asks the person who invites to prove it is them again (the password and
// a code when two-step is on). The proof goes in the body next to the email and role. POST /invitations takes { email, role } and answers { detail, email_sent, invite_link }. The link is returned
// either way. When the email did not go out the admin has to pass the link on by hand, so it is shown with a copy
// button and a plain note.
export default function InviteForm({ onInvited }: { onInvited: () => void }) {
  const [email, setEmail] = useState('');
  const [role, setRole] = useState('viewer');
  const [pending, setPending] = useState(false);
  const [emailError, setEmailError] = useState('');
  const [formError, setFormError] = useState('');
  const [reference, setReference] = useState<string | null>(null);
  const idem = useIdempotencyKey();
  const [result, setResult] = useState<InviteResult | null>(null);
  const [copied, setCopied] = useState(false);
  const [asking, setAsking] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setEmailError('');
    setFormError('');
    setReference(null);
    setResult(null);
    setCopied(false);
    if (role === 'admin') {
      setAsking(true);
      return;
    }
    setPending(true);
    try {
      await send({});
    } catch (err) {
      const info = errorInfo(err);
      // the only field-level refusals are about the address (an account that already exists) and they come by code
      if ((info.code === 'account_exists' || info.code === 'email_in_use') && info.detail) setEmailError(info.detail);
      else {
        setFormError(info.detail ?? describeApiError(err, 'The invitation'));
        setReference(info.requestId ?? null);
      }
    } finally {
      setPending(false);
    }
  }

  // sends the invitation with the proof (none for a viewer or a technician) and shows the result
  async function send(proof: Proof) {
    // one Idempotency-Key for this invitation, kept across a retry, so a double click cannot send it twice
    const { data } = await api.post<{ email_sent?: boolean; invite_link: string }>('/invitations', { email, role, ...proof }, idempotent(idem.keyFor(JSON.stringify({ email, role }))));
    idem.renew();
    setResult({ email, email_sent: data.email_sent === true, invite_link: data.invite_link });
    setEmail('');
    onInvited();
  }

  async function copy() {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.invite_link);
      setCopied(true);
    } catch {
      setCopied(false);
      setFormError('The link could not be copied. Select it and copy it by hand.');
    }
  }

  return (
    <Panel title="Invite a user" description="They get a link that is valid for 48 hours and choose their own password.">
      <form onSubmit={submit} noValidate className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <Input
            label="Email address"
            type="email"
            autoComplete="off"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            error={emailError || undefined}
            wrapperClassName="min-h-[100px]"
          />
          <Select label="Role" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="viewer">Viewer</option>
            <option value="technician">Technician</option>
            <option value="admin">Admin</option>
          </Select>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" pending={pending}>Send invitation</Button>
          <p role="alert" className="min-h-5 text-base font-medium text-critical-800 dark:text-critical-300">{formError}</p>
          {formError && <RequestRef id={reference} />}
        </div>
      </form>

      <div role="status" className="mt-4 empty:mt-0">
        {result && result.email_sent && (
          <p className="text-base text-surface-900 dark:text-surface-50">Invitation emailed to {result.email}.</p>
        )}
        {result && !result.email_sent && (
          <div className="space-y-3">
            <p className="text-base text-surface-900 dark:text-surface-50">
              The invitation was created but the email was not sent. Send {result.email} this link yourself.
            </p>
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-0 flex-1">
                <Input label="Invitation link" readOnly value={result.invite_link} onFocus={(e) => e.currentTarget.select()} className="num" />
              </div>
              <Button variant="secondary" onClick={copy} icon={copied ? <CheckIcon /> : <CopyIcon />}>{copied ? 'Copied' : 'Copy link'}</Button>
            </div>
          </div>
        )}
      </div>
      <ProofDialog open={asking} title="Invite an admin?" confirmLabel="Send invitation" onCancel={() => setAsking(false)} run={(proof) => send(proof)} onDone={() => setAsking(false)} returnTo="/admin">
        <p>{email} will be able to change everything in PHAEMOS: machines, rules, webhooks, firmware and other people.</p>
      </ProofDialog>
    </Panel>
  );
}
