'use client';

import { useReducer, useRef, useState } from 'react';
import api from '@/lib/api';
import { useApiResource } from '@/hooks/useApiResource';
import { useIdempotencyKey } from '@/hooks/useIdempotencyKey';
import { idempotent } from '@/lib/idempotency';
import { errorInfo } from '@/lib/apiCode';
import { describeApiError } from '@/lib/apiError';
import { CLOSED, keyReducer } from '@/lib/keyOnce';
import { deliveryState, failedTest, formatLabel, formatOf, secretFromAnswer, testOutcome, testSentence, VERIFY_LINK, WEBHOOK_FORMATS, type Webhook, type WebhookFormat } from '@/lib/webhooks';
import Button from '@/components/ui/Button';
import Checkbox from '@/components/ui/Checkbox';
import ConfirmDialog from '@/components/ui/ConfirmDialog';
import DataTable from '@/components/ui/DataTable';
import EmptyState from '@/components/ui/EmptyState';
import ErrorNotice from '@/components/ui/ErrorNotice';
import { Input, Textarea } from '@/components/ui/Input';
import Panel from '@/components/ui/Panel';
import ProofDialog, { type Proof } from '@/components/ui/ProofDialog';
import RequestRef from '@/components/ui/RequestRef';
import { SkeletonRows } from '@/components/ui/Skeleton';
import { StatusShape } from '@/components/ui/StatusBadge';
import Time from '@/components/ui/Time';
import { TONE_TEXT } from '@/components/ui/tone';
import Pager from './Pager';
import SecretOnceDialog from './SecretOnceDialog';

// the list is paged at 50 by default and the page size is stated here so the pager and the request agree
const PAGE_SIZE = 50;

const TONE = { ok: 'success', failing: 'critical', off: 'neutral', none: 'neutral' } as const;
const SHAPE = { ok: 'circle', failing: 'triangle', off: 'ring', none: 'ring' } as const;

type Asking = { kind: 'create' } | { kind: 'toggle'; wh: Webhook } | { kind: 'rotate'; wh: Webhook };

// a webhook sends every alert to an address the admin chooses, so creating one, changing one or making a new signing secret asks the admin
// to prove it is them again first (the password and a code when two-step is on). The proof goes in the request body next to the webhook's
// own fields. A signed JSON webhook has a secret that the API shows once, in the answer that makes it or rotates it.
export default function WebhooksPanel() {
  const [skip, setSkip] = useState(0);
  const { data, error, loading, retry, total } = useApiResource<Webhook[]>('/webhooks', { params: { limit: PAGE_SIZE, offset: skip }, what: 'The webhooks' });

  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [format, setFormat] = useState<WebhookFormat>('chat');
  const [template, setTemplate] = useState('');
  const [errors, setErrors] = useState<{ name?: string; url?: string; template?: string }>({});
  const [refs, setRefs] = useState<{ url?: string; template?: string }>({});
  const [asking, setAsking] = useState<Asking | null>(null);
  const idem = useIdempotencyKey();

  // the secret passes from the request to the dialog through a ref and is cleared as it is handed over, so it is never in React state while the proof dialog is open
  const secretIn = useRef<string | null>(null);
  // what the last proof run did to the form, read by done() to decide between a notice and a message beside a field
  const outcome = useRef<'ok' | 'field'>('ok');
  const [secret, dispatchSecret] = useReducer(keyReducer, CLOSED);
  const [secretFor, setSecretFor] = useState<{ name: string; rotated: boolean }>({ name: '', rotated: false });

  const [notice, setNotice] = useState('');
  const [actionError, setActionError] = useState('');
  const [actionRef, setActionRef] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [toDelete, setToDelete] = useState<Webhook | null>(null);
  const [deleting, setDeleting] = useState(false);

  function openForm() {
    idem.renew();
    setErrors({});
    setRefs({});
    setShowForm(true);
  }

  function create(e: React.FormEvent) {
    e.preventDefault();
    const next: typeof errors = {};
    if (!name.trim()) next.name = 'Enter a name.';
    if (!/^https?:\/\/\S+$/i.test(url.trim())) next.url = 'Enter the full URL, starting with https://.';
    setErrors(next);
    setRefs({});
    if (Object.keys(next).length) return;
    setAsking({ kind: 'create' });
  }

  async function runChange(proof: Proof) {
    if (!asking) return;
    outcome.current = 'ok';
    if (asking.kind === 'create') {
      const body = { name: name.trim(), url: url.trim(), enabled: true, format, template: format === 'chat' && template.trim() ? template : null };
      try {
        const res = await api.post('/webhooks', { ...body, ...proof }, idempotent(idem.keyFor(JSON.stringify(body))));
        secretIn.current = secretFromAnswer(res.data);
      } catch (err) {
        // a refusal about one field is said beside that field, not in the dialog
        const info = errorInfo(err);
        if (info.code === 'webhook_url_refused') setErrors({ url: info.detail ?? 'That address is not allowed.' }), setRefs({ url: info.requestId });
        else if (info.code === 'webhook_template_invalid') setErrors({ template: info.detail ?? 'The template is not valid.' }), setRefs({ template: info.requestId });
        else throw err;
        outcome.current = 'field';
      }
    } else if (asking.kind === 'toggle') {
      await api.patch(`/webhooks/${asking.wh.id}`, { enabled: !asking.wh.enabled, ...proof });
    } else {
      const res = await api.post(`/webhooks/${asking.wh.id}/rotate-secret`, proof);
      secretIn.current = secretFromAnswer(res.data);
    }
  }

  function done() {
    const a = asking;
    setAsking(null);
    if (!a || outcome.current === 'field') return;
    const s = secretIn.current;
    secretIn.current = null;
    if (a.kind === 'create') {
      idem.renew();
      setSecretFor({ name: name.trim(), rotated: false });
      setNotice(`Webhook ${name.trim()} added.`);
      setName('');
      setUrl('');
      setTemplate('');
      setFormat('chat');
      setShowForm(false);
    } else if (a.kind === 'toggle') {
      setNotice(`${a.wh.name} is now ${a.wh.enabled ? 'off' : 'on'}.`);
    } else {
      setSecretFor({ name: a.wh.name, rotated: true });
      setNotice(s ? `${a.wh.name} has a new signing secret.` : '');
      if (!s) setActionError('The secret was replaced but the answer did not carry the new one. Make a new secret again.');
    }
    if (s) dispatchSecret({ type: 'show', key: s });
    setSkip(0);
    retry();
  }

  async function test(wh: Webhook) {
    setTestingId(wh.id);
    setActionError('');
    setActionRef(null);
    setNotice('');
    try {
      const res = await api.post(`/webhooks/${wh.id}/test`);
      const o = testOutcome(res.data);
      if (o.ok) setNotice(testSentence(wh.name, o));
      else setActionError(testSentence(wh.name, o));
    } catch (err) {
      const failed = failedTest(err);
      const info = errorInfo(err);
      if (failed) {
        setActionError(testSentence(wh.name, { ok: false, status: failed.status, elapsedMs: failed.elapsedMs }) + (failed.status === null ? ' Nothing answered.' : ''));
        setActionRef(info.requestId ?? null);
      } else if (info.code === 'webhook_url_refused') {
        setActionError(info.detail ?? 'That address is not allowed.');
        setActionRef(info.requestId ?? null);
      } else {
        setActionError(info.detail ?? describeApiError(err, 'The test'));
        setActionRef(info.requestId ?? null);
      }
    } finally {
      setTestingId(null);
      // the outcome is kept on the webhook, so the list is read again to show it
      retry();
    }
  }

  async function confirmDelete() {
    if (!toDelete) return;
    setDeleting(true);
    try {
      await api.delete(`/webhooks/${toDelete.id}`);
      setNotice(`Webhook ${toDelete.name} deleted.`);
      setToDelete(null);
      // a page that held only this webhook goes back one
      if (data && data.length === 1 && skip > 0) setSkip(Math.max(0, skip - PAGE_SIZE));
      retry();
    } catch (err) {
      setToDelete(null);
      setActionError(errorInfo(err).detail ?? describeApiError(err, 'The webhook'));
      setActionRef(errorInfo(err).requestId ?? null);
    } finally {
      setDeleting(false);
    }
  }

  const askTitle = asking?.kind === 'toggle' ? `Turn ${asking.wh.name} ${asking.wh.enabled ? 'off' : 'on'}?` : asking?.kind === 'rotate' ? `Make a new signing secret for ${asking.wh.name}?` : 'Add this webhook?';
  const askLabel = asking?.kind === 'toggle' ? (asking.wh.enabled ? 'Turn off' : 'Turn on') : asking?.kind === 'rotate' ? 'Make new secret' : 'Add webhook';

  return (
    <div className="space-y-6">
      {showForm && (
        <Panel title="New webhook" description="We post each alert to this URL. The address must start with https:// and point at a public server.">
          <form onSubmit={create} noValidate className="max-w-xl space-y-4">
            <Input label="Name" required value={name} onChange={(e) => setName(e.target.value)} error={errors.name} wrapperClassName="min-h-[100px]" />
            <Input
              label="URL"
              required
              type="url"
              inputMode="url"
              value={url}
              onChange={(e) => { setUrl(e.target.value); setErrors((x) => ({ ...x, url: undefined })); }}
              error={errors.url}
              wrapperClassName="min-h-[100px]"
            />
            {refs.url && <RequestRef id={refs.url} />}
            <fieldset className="space-y-1">
              <legend className="text-base font-medium text-surface-900 dark:text-surface-50">Format</legend>
              {WEBHOOK_FORMATS.map((f) => (
                <label key={f.value} className="flex min-h-[44px] cursor-pointer items-start gap-3 py-2 text-base text-surface-900 dark:text-surface-50">
                  <input type="radio" name="webhook-format" value={f.value} checked={format === f.value} onChange={() => { setFormat(f.value); setErrors((x) => ({ ...x, template: undefined })); }} className="mt-1" />
                  <span>
                    <span className="font-medium">{f.label}</span>
                    <span className="block text-surface-700 dark:text-surface-300">{f.sentence}</span>
                  </span>
                </label>
              ))}
            </fieldset>
            {format === 'chat' ? (
              <>
                <Textarea
                  label="Message template (optional)"
                  hint="Plain text. You can use {severity}, {metric}, {device_name}, {value} and {threshold}. Nothing else is allowed. Leave it empty for the default message."
                  rows={3}
                  value={template}
                  onChange={(e) => { setTemplate(e.target.value); setErrors((x) => ({ ...x, template: undefined })); }}
                  error={errors.template}
                  className="font-mono"
                />
                {refs.template && <RequestRef id={refs.template} />}
              </>
            ) : (
              <p className="text-base text-surface-800 dark:text-surface-200">
                A signed JSON webhook sends the alert as it is and takes no template. The secret is shown once, when you add it. The <a href={VERIFY_LINK} className="underline underline-offset-2" target="_blank" rel="noopener noreferrer">API reference<span className="sr-only"> (opens in a new tab)</span></a> shows how a receiver checks the signature.
              </p>
            )}
            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit">Save webhook</Button>
              <Button variant="secondary" onClick={() => setShowForm(false)}>Cancel</Button>
            </div>
          </form>
        </Panel>
      )}

      <Panel title="Webhooks" bodyClassName="p-0" actions={!showForm ? <Button onClick={openForm}>Add webhook</Button> : undefined}>
        {loading && !data ? (
          <div className="p-4"><SkeletonRows rows={3} label="Loading webhooks" /></div>
        ) : error && !data ? (
          <div className="p-4"><ErrorNotice message={error} onRetry={retry} /></div>
        ) : data && data.length === 0 && skip === 0 ? (
          <EmptyState heading="No webhooks yet" subMessage="Add one to send alerts to Slack, Discord or Teams or to a program as signed JSON." />
        ) : data ? (
          <>
            {error && <div className="p-4"><ErrorNotice message={error} onRetry={retry} /></div>}
            <DataTable caption="Webhooks">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">URL</th>
                  <th scope="col">Format</th>
                  <th scope="col">Last delivery</th>
                  <th scope="col">Alerts</th>
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {data.map((wh) => {
                  const state = deliveryState(wh);
                  return (
                    <tr key={wh.id}>
                      <td>{wh.name}</td>
                      <td className="max-w-[18rem] break-all">{wh.url}</td>
                      <td>{formatLabel(formatOf(wh))}</td>
                      <td className="max-w-[20rem]">
                        <span className={`inline-flex items-center gap-1.5 font-medium ${TONE_TEXT[TONE[state.tone]]}`}>
                          <StatusShape shape={SHAPE[state.tone]} />
                          <span className="text-surface-900 dark:text-surface-50">{state.label}</span>
                        </span>
                        <span className="block text-meta text-surface-700 dark:text-surface-300">
                          {wh.last_delivery_at && state.tone !== 'off' && <><Time value={wh.last_delivery_at} format="relative" />. </>}
                          {state.detail}
                        </span>
                      </td>
                      <td>
                        <Checkbox className="-my-1.5" label="On" aria-label={`On, ${wh.name}`} checked={wh.enabled} onChange={() => { setActionError(''); setActionRef(null); setAsking({ kind: 'toggle', wh }); }} />
                      </td>
                      <td>
                        <div className="flex flex-wrap justify-end gap-2">
                          <Button size="small" variant="secondary" pending={testingId === wh.id} onClick={() => test(wh)} aria-label={`Send a test to ${wh.name}`}>Test</Button>
                          {formatOf(wh) === 'json' && (
                            <Button size="small" variant="secondary" onClick={() => { setActionError(''); setActionRef(null); setAsking({ kind: 'rotate', wh }); }} aria-label={`Make a new signing secret for ${wh.name}`}>New secret</Button>
                          )}
                          <Button size="small" variant="secondary" onClick={() => setToDelete(wh)} aria-label={`Delete ${wh.name}`}>Delete</Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </DataTable>
            <Pager skip={skip} shown={data.length} pageSize={PAGE_SIZE} total={total} onChange={setSkip} what="Webhooks" />
          </>
        ) : null}
      </Panel>

      <div className="min-h-5">
        <p role="status" className="text-base text-surface-900 dark:text-surface-50">{notice}</p>
        {actionError && <ErrorNotice message={actionError} />}
        {actionError && <RequestRef id={actionRef} />}
      </div>

      <ConfirmDialog open={toDelete !== null} title="Delete this webhook?" confirmLabel="Delete webhook" onCancel={() => setToDelete(null)} onConfirm={confirmDelete} pending={deleting}>
        {toDelete && <p>We will stop sending alerts to {toDelete.name} ({toDelete.url}). This cannot be undone.</p>}
      </ConfirmDialog>
      <ProofDialog open={asking !== null} title={askTitle} confirmLabel={askLabel} onCancel={() => setAsking(null)} run={runChange} onDone={done} returnTo="/admin">
        <p>
          {asking?.kind === 'toggle'
            ? 'Alerts are posted to this address while it is on.'
            : asking?.kind === 'rotate'
              ? 'The old secret stops signing at once, so update the receiver first. The new secret is shown once.'
              : `Every alert will be posted to ${url}.${format === 'json' ? ' The signing secret is shown once, after this.' : ''}`}
        </p>
      </ProofDialog>
      <SecretOnceDialog state={secret} dispatch={dispatchSecret} webhookName={secretFor.name} rotated={secretFor.rotated} />
    </div>
  );
}
