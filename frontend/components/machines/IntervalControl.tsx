'use client';

import { useState } from 'react';
import api from '@/lib/api';
import { describeApiError } from '@/lib/apiError';
import type { Device } from '@/types';
import Button from '@/components/ui/Button';
import ErrorNotice from '@/components/ui/ErrorNotice';
import { Input } from '@/components/ui/Input';

interface Props {
  deviceId: string;
  // seconds between posts as the API reports it
  current: number;
  onSaved: (seconds: number) => void;
}

// the interval is how often this node posts. An admin sets it when a node posts slower or faster than the usual 5 seconds, so
// the monitoring link does not read late for a node that is simply slow. The API takes 1 to 86400 and answers 403 to anyone else.
export default function IntervalControl({ deviceId, current, onSaved }: Props) {
  const [value, setValue] = useState(String(current));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const n = Number(value);
  const valid = Number.isInteger(n) && n >= 1 && n <= 86400;
  const changed = valid && n !== current;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!changed) return;
    setPending(true);
    setError(null);
    setSaved(false);
    try {
      const res = await api.patch<Device>(`/devices/${deviceId}`, { expected_interval_s: n });
      onSaved(res.data.expected_interval_s ?? n);
      setSaved(true);
    } catch (err) {
      setError(describeApiError(err, 'The machine'));
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={save} className="mt-5 max-w-xl border-t border-surface-200 pt-4 dark:border-surface-800">
      <div className="flex flex-wrap items-start gap-3">
        <Input
          label="Seconds between posts"
          type="number"
          inputMode="numeric"
          min={1}
          max={86400}
          step={1}
          value={value}
          onChange={(e) => { setValue(e.target.value); setSaved(false); }}
          error={value !== '' && !valid ? 'Enter a whole number from 1 to 86400.' : undefined}
          hint="How often this node posts a reading. The link reads late after 4 times this and offline after 12 times it and the anomaly alert looks at a window of at least two minutes or 24 readings. Leave it at 5 unless the node posts slower or faster."
          wrapperClassName="min-w-48 flex-1"
        />
        <Button type="submit" variant="secondary" pending={pending} disabled={!changed} className="mt-[26px]">Save</Button>
      </div>
      {error && <ErrorNotice className="mt-3" message="The interval was not saved." detail={error} />}
      <p role="status" className="mt-2 text-sm text-surface-800 dark:text-surface-200">{saved ? 'Saved.' : ''}</p>
    </form>
  );
}
