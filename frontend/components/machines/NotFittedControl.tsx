'use client';

import { useState } from 'react';
import api from '@/lib/api';
import { describeApiError } from '@/lib/apiError';
import type { Device } from '@/types';
import Button from '@/components/ui/Button';
import Checkbox from '@/components/ui/Checkbox';
import ErrorNotice from '@/components/ui/ErrorNotice';
import { knownSensorKeys, sensorName } from '@/lib/machineState';

interface Props {
  deviceId: string;
  // the sensor keys now marked as not fitted
  current: readonly string[];
  onSaved: (notFitted: string[]) => void;
}

// every key the API stores, in the order the sensor map lists them, with the plain names. Admins only: the API answers 403
// to anyone else, so the page does not render this for them.
const KEYS = knownSensorKeys();

// an admin marks the sensors a machine does not have, such as a hub with no vibration node. A fault reported on one of them
// raises no alert and never makes the machine unknown.
export default function NotFittedControl({ deviceId, current, onSaved }: Props) {
  const [picked, setPicked] = useState<string[]>([...current]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const changed = picked.length !== current.length || picked.some((k) => !current.includes(k));

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    setSaved(false);
    try {
      const res = await api.patch<Device>(`/devices/${deviceId}`, { not_fitted: picked });
      onSaved(res.data.not_fitted ?? picked);
      setSaved(true);
    } catch (err) {
      setError(describeApiError(err, 'The machine'));
    } finally {
      setPending(false);
    }
  }

  const label = current.length === 0 ? 'Sensors not fitted: none marked' : `Sensors not fitted: ${current.length} marked`;

  return (
    <details className="mt-6 border-t border-surface-200 pt-2 dark:border-surface-800">
      <summary className="flex min-h-[44px] cursor-pointer items-center text-base font-semibold text-surface-900 dark:text-surface-50">{label}</summary>
      <form onSubmit={save} className="pt-2">
        <fieldset>
          <legend className="max-w-[72ch] text-sm font-normal text-surface-700 dark:text-surface-300">
            Tick a sensor that this machine does not have. A fault on it then raises no alert and never makes the machine unknown. Only admins see this.
          </legend>
          <div className="mt-2 grid grid-cols-[minmax(0,1fr)] sm:grid-cols-2 lg:grid-cols-3">
            {KEYS.map((key) => (
              <Checkbox
                key={key}
                label={sensorName(key, true)}
                checked={picked.includes(key)}
                onChange={(e) => setPicked((p) => (e.target.checked ? [...p, key] : p.filter((k) => k !== key)))}
              />
            ))}
          </div>
        </fieldset>
        {error && <ErrorNotice className="mt-3" message="The change was not saved." detail={error} />}
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button type="submit" variant="secondary" pending={pending} disabled={!changed}>Save sensors</Button>
          <p role="status" className="text-sm text-surface-800 dark:text-surface-200">{saved ? 'Saved.' : ''}</p>
        </div>
      </form>
    </details>
  );
}
