'use client';

import { useState } from 'react';
import api from '@/lib/api';
import { apiDetail } from '@/lib/apiDetail';
import { describeApiError } from '@/lib/apiError';
import Button from '@/components/ui/Button';
import Field from '@/components/ui/Field';
import { Input } from '@/components/ui/Input';
import Panel from '@/components/ui/Panel';
import ProofDialog, { type Proof } from '@/components/ui/ProofDialog';

// POST /firmware/upload?version=... with the file as multipart form data. The API keeps one file at a time and
// refuses anything over 2 MB that is not a .bin. A firmware file is run by every node, so uploading one asks the admin to prove it is
// them again first. The proof goes in the form beside the file (the password and, when two-step is on, a code).
export default function FirmwarePanel() {
  const [version, setVersion] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [fileKey, setFileKey] = useState(0);
  const [pending, setPending] = useState(false);
  const [versionError, setVersionError] = useState('');
  const [fileError, setFileError] = useState('');
  const [failure, setFailure] = useState('');
  const [done, setDone] = useState('');
  const [asking, setAsking] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setDone('');
    setFailure('');
    const vErr = version.trim() ? '' : 'Enter a version.';
    const fErr = !file ? 'Choose a .bin file.' : !file.name.endsWith('.bin') ? 'Only .bin firmware files are accepted.' : '';
    setVersionError(vErr);
    setFileError(fErr);
    if (vErr || fErr || !file) return;
    setAsking(true);
  }

  // use FormData to send the binary file as a multipart upload, with the proof as two more fields
  async function upload(proof: Proof) {
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    if (proof.password) form.append('password', proof.password);
    if (proof.code) form.append('code', proof.code);
    setPending(true);
    try {
      await api.post(`/firmware/upload?version=${encodeURIComponent(version)}`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
    } catch (err) {
      // a file that is too big is a fact about the file, not about the proof: say it on the page and close the dialog
      const status = (err as { response?: { status?: number } }).response?.status;
      if (status === 413) {
        setAsking(false);
        setFailure('The file is over the 2 MB limit.');
        return;
      }
      throw err;
    } finally {
      setPending(false);
    }
    setDone(`Firmware ${version} uploaded. Nodes install it the next time they start.`);
    setVersion('');
    setFile(null);
    // a file input cannot be cleared through its value in React, so a new key remounts it
    setFileKey((k) => k + 1);
  }

  return (
    <Panel title="Upload firmware" description="Upload a compiled .bin file. Each ESP32 node installs it the next time it starts if the version is newer. Files can be up to 2 MB.">
      <form onSubmit={submit} noValidate className="max-w-md space-y-4">
        <Input label="Version" required value={version} onChange={(e) => setVersion(e.target.value)} error={versionError || undefined} hint="For example 1.1.0" wrapperClassName="min-h-[124px]" className="num" />
        <Field label="Firmware file (.bin)" required error={fileError || undefined} className="min-h-[100px]">
          {(c) => (
            <input
              {...c}
              key={fileKey}
              type="file"
              accept=".bin"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block w-full text-base text-surface-900 file:mr-3 file:min-h-[44px] file:cursor-pointer file:rounded-md file:border file:border-surface-500 file:bg-surface-0 file:px-4 file:text-base file:font-medium file:text-surface-900 dark:text-surface-50 dark:file:bg-surface-900 dark:file:text-surface-50"
            />
          )}
        </Field>
        <Button type="submit" pending={pending}>Upload firmware</Button>
        <p role="status" className="min-h-5 text-base text-surface-900 dark:text-surface-50">{done}</p>
        <p role="alert" className="min-h-5 text-base font-medium text-critical-800 dark:text-critical-300">{failure}</p>
      </form>
      <ProofDialog open={asking} title="Upload this firmware?" confirmLabel="Upload firmware" onCancel={() => setAsking(false)} run={(proof) => upload(proof)} onDone={() => setAsking(false)} returnTo="/admin">
        <p>Every ESP32 node installs version {version} the next time it starts, if that is newer than what it runs.</p>
      </ProofDialog>
    </Panel>
  );
}
