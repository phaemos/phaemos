'use client';

import { useRef, useState } from 'react';
import api from '@/lib/api';
import { idempotent, newIdempotencyKey } from '@/lib/idempotency';
import { requestIdOf } from '@/lib/apiCode';
import { describeApiError } from '@/lib/apiError';
import { useApiResource } from '@/hooks/useApiResource';
import type { Device } from '@/types';
import Button from '@/components/ui/Button';
import ErrorNotice from '@/components/ui/ErrorNotice';
import { Input, Select, Textarea } from '@/components/ui/Input';
import { PRIORITY_ORDER, TICKET_PRIORITY } from '@/lib/status';

export interface TicketPrefill {
  device_id?: string;
  // shown when the machine list has not loaded or does not hold this machine
  device_name?: string;
  description?: string;
  title?: string;
}

interface TicketFormProps {
  onSuccess?: () => void;
  onCancel?: () => void;
  prefill?: TicketPrefill;
}

// the machines one request asks for, so a fleet past the API default of 20 still appears in the list
const DEVICE_LIMIT = 200;

export default function TicketForm({ onSuccess, onCancel, prefill }: TicketFormProps) {
  const [title, setTitle] = useState(prefill?.title ?? '');
  const [description, setDescription] = useState(prefill?.description ?? '');
  const [priority, setPriority] = useState('medium');
  const [deviceId, setDeviceId] = useState(prefill?.device_id ?? '');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [titleError, setTitleError] = useState<string | undefined>();

  // machines are picked by name and the form still sends the machine id the API expects
  const machines = useApiResource<Device[]>('/devices', { params: { limit: DEVICE_LIMIT }, what: 'The machine list' });
  const listed = machines.data ?? [];
  const prefilledMissing = Boolean(prefill?.device_id) && !listed.some((d) => d.id === prefill?.device_id);

  // one Idempotency-Key for this submission, kept across retries so a create that timed out is never made twice
  const submission = useRef<string | null>(null);
  const [reference, setReference] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!title.trim()) {
      setTitleError('Enter a title.');
      return;
    }
    setTitleError(undefined);
    setSubmitting(true);
    setError(null);
    try {
      // send only fields the person filled in: the API treats an omitted optional field as empty
      await api.post('/tickets', {
        title: title.trim(),
        description: description || undefined,
        priority: priority || undefined,
        device_id: deviceId || undefined,
      }, idempotent((submission.current ??= newIdempotencyKey())));
      submission.current = null;
      onSuccess?.();
    } catch (err: unknown) {
      setError(describeApiError(err, 'The ticket'));
      setReference(requestIdOf(err) ?? null);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      {error && <ErrorNotice message="The ticket was not created." detail={error} requestId={reference} />}
      <Input
        label="Title"
        required
        maxLength={200}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        error={titleError}
        placeholder="Short description of the issue"
        data-autofocus=""
      />
      <Textarea
        label="Description"
        maxLength={5000}
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="What you saw and what needs doing"
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <Select label="Priority" value={priority} onChange={(e) => setPriority(e.target.value)}>
          {[...PRIORITY_ORDER].reverse().map((p) => (
            <option key={p} value={p}>{TICKET_PRIORITY[p].word}</option>
          ))}
        </Select>
        <Select
          label="Machine"
          value={deviceId}
          onChange={(e) => setDeviceId(e.target.value)}
          hint={machines.error ? 'The machine list did not load. You can still create the ticket.' : undefined}
        >
          <option value="">No specific machine</option>
          {prefilledMissing && prefill?.device_id && <option value={prefill.device_id}>{prefill.device_name ?? 'The machine on this alert'}</option>}
          {listed.map((d) => (
            <option key={d.id} value={d.id}>{d.name}{d.location ? ` (${d.location})` : ''}</option>
          ))}
        </Select>
      </div>
      <div className="flex flex-wrap justify-end gap-3 pt-1">
        {onCancel && <Button variant="secondary" onClick={onCancel} disabled={submitting}>Cancel</Button>}
        <Button type="submit" pending={submitting}>Create ticket</Button>
      </div>
    </form>
  );
}
