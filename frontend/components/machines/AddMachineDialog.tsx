'use client';

import { useRef, useState } from 'react';
import axios from 'axios';
import api from '@/lib/api';
import { describeApiError } from '@/lib/apiError';
import type { Device, User } from '@/types';
import ConfirmDialog from '@/components/ui/ConfirmDialog';
import ErrorNotice from '@/components/ui/ErrorNotice';
import { Input, Select } from '@/components/ui/Input';
import { NODE_TYPES } from '@/lib/nodeTypes';
import { keyFromAnswer } from '@/lib/keyOnce';
import { idempotent, newIdempotencyKey } from '@/lib/idempotency';
import { requestIdOf } from '@/lib/apiCode';

interface Props {
  open: boolean;
  onClose: () => void;
  // admins only: the people a machine can be assigned to
  users: User[];
  // POST /devices answers with the machine and its API key, which no other route returns. The key is handed on at once to the page's
  // one-time key dialog (KeyOnceDialog) and this dialog keeps nothing of it.
  onCreated: (machine: { id: string; name: string }, key: string | null) => void;
}

function createError(err: unknown): string {
  if (axios.isAxiosError(err) && err.response?.status === 422) return 'The details were not accepted. A name is required and no field may be longer than 200 characters.';
  if (axios.isAxiosError(err) && err.response?.status === 403) return 'Only admins can add machines.';
  return describeApiError(err, 'The machine');
}

// the parent gives the dialog a new key each time it opens, so the fields and the key never survive a close
export default function AddMachineDialog({ open, onClose, users, onCreated }: Props) {
  const [name, setName] = useState('');
  const [location, setLocation] = useState('');
  const [type, setType] = useState('');
  const [owner, setOwner] = useState('');
  const [nameError, setNameError] = useState<string | undefined>();
  const [failure, setFailure] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [reference, setReference] = useState<string | null>(null);
  const submission = useRef<string | null>(null);

  async function submit() {
    const trimmed = name.trim();
    setFailure(null);
    if (!trimmed) {
      setNameError('Enter a name for the machine.');
      return;
    }
    setNameError(undefined);
    setPending(true);
    try {
      // the API takes name, location, type and owner_id. Tags are added afterwards on the machine page
      // the same Idempotency-Key on every retry of this form: a create that timed out returns its first answer, key included and makes
      // no second machine
      const res = await api.post<Device>('/devices', {
        name: trimmed,
        location: location.trim() || null,
        type: type || null,
        owner_id: owner || null,
      }, idempotent((submission.current ??= newIdempotencyKey())));
      submission.current = null;
      onCreated({ id: res.data.id, name: res.data.name }, keyFromAnswer(res.data));
    } catch (err) {
      setFailure(createError(err));
      setReference(requestIdOf(err) ?? null);
    } finally {
      setPending(false);
    }
  }

  return (
    <ConfirmDialog
      open={open}
      title="Add a machine"
      confirmLabel="Add machine"
      destructive={false}
      pending={pending}
      onCancel={onClose}
      onConfirm={submit}
    >
      <div className="space-y-4">
        <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} error={nameError} maxLength={200} required autoComplete="off" />
        <Input label="Location" value={location} onChange={(e) => setLocation(e.target.value)} maxLength={200} autoComplete="off" />
        <Select label="Node type" value={type} onChange={(e) => setType(e.target.value)} hint="The board attached to the machine.">
          <option value="">Not set</option>
          {NODE_TYPES.map((n) => <option key={n.value} value={n.value}>{n.label}</option>)}
        </Select>
        <Select label="Owner" value={owner} onChange={(e) => setOwner(e.target.value)}>
          <option value="">Unassigned</option>
          {users.map((u) => <option key={u.id} value={u.id}>{u.name ?? u.email} ({u.role})</option>)}
        </Select>
        {failure && <ErrorNotice message={failure} requestId={reference} />}
      </div>
    </ConfirmDialog>
  );
}
