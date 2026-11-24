'use client';

import { useState } from 'react';
import axios from 'axios';
import api from '@/lib/api';
import { describeApiError } from '@/lib/apiError';
import ConfirmDialog from '@/components/ui/ConfirmDialog';
import ErrorNotice from '@/components/ui/ErrorNotice';
import { Input, Select } from '@/components/ui/Input';
import { machineCount } from '@/lib/machineList';

interface Props {
  open: boolean;
  onClose: () => void;
  // every tag in use with the number of machines that carry it
  tags: { tag: string; count: number }[];
  onQueued: (message: string) => void;
}

interface Queued {
  queued: number;
  tag: string;
  target_version: string;
}

// POST /devices/batch/firmware-update takes one tag and one version and sets that target version on every machine
// carrying the tag. It cannot target chosen machines, so this chooses by tag and the list has no row checkboxes;
// the parent gives the dialog a new key each time it opens, so the fields start empty.
export default function FirmwareDialog({ open, onClose, tags, onQueued }: Props) {
  const [tag, setTag] = useState('');
  const [version, setVersion] = useState('');
  const [errors, setErrors] = useState<{ tag?: string; version?: string }>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const chosen = tags.find((t) => t.tag === tag);

  async function submit() {
    const next: typeof errors = {};
    if (!tag) next.tag = tags.length === 0 ? 'No machine has a tag yet. Add one on a machine page first.' : 'Choose a tag.';
    if (!version.trim()) next.version = 'Enter the version to install.';
    setErrors(next);
    setFailure(null);
    if (next.tag || next.version) return;
    setPending(true);
    try {
      const res = await api.post<Queued>('/devices/batch/firmware-update', { tag, version: version.trim() });
      onQueued(`Firmware ${res.data.target_version} set for ${machineCount(res.data.queued)} tagged ${res.data.tag}.`);
      onClose();
    } catch (err) {
      setFailure(axios.isAxiosError(err) && err.response?.status === 403 ? 'Only admins can update firmware.' : describeApiError(err, 'The firmware update'));
    } finally {
      setPending(false);
    }
  }

  return (
    <ConfirmDialog
      open={open}
      title="Update firmware by tag"
      confirmLabel={chosen ? `Update ${machineCount(chosen.count)}` : 'Update machines'}
      destructive={false}
      pending={pending}
      onCancel={onClose}
      onConfirm={submit}
    >
      <div className="space-y-4">
        <p>
          This sets the target version on every machine that carries the tag. Each node picks it up the next time it checks for firmware.
          It does not upload a file: upload the firmware on the Admin page first.
        </p>
        <Select label="Tag" value={tag} onChange={(e) => setTag(e.target.value)} error={errors.tag} required>
          <option value="">Choose a tag</option>
          {tags.map((t) => <option key={t.tag} value={t.tag}>{t.tag} ({machineCount(t.count)})</option>)}
        </Select>
        <Input label="Target version" value={version} onChange={(e) => setVersion(e.target.value)} error={errors.version} hint="For example 1.2.0" maxLength={100} required autoComplete="off" />
        {failure && <ErrorNotice message={failure} />}
      </div>
    </ConfirmDialog>
  );
}
