'use client';

import { useReducer, useRef, useState } from 'react';
import api from '@/lib/api';
import Button from '@/components/ui/Button';
import ProofDialog, { type Proof } from '@/components/ui/ProofDialog';
import { CLOSED, keyFromAnswer, keyReducer } from '@/lib/keyOnce';
import KeyOnceDialog from './KeyOnceDialog';

interface Props {
  deviceId: string;
  machineName: string;
}

// replaces a machine's API key. The API shows a key only in this answer and in the one that creates a machine and it stops the old key
// at once, so the person is told that before they start and is shown the new key once in KeyOnceDialog. The request carries the
// password (and the two-step code when it is on) in its body, gathered by ProofDialog.
export default function RotateKeyControl({ deviceId, machineName }: Props) {
  const [asking, setAsking] = useState(false);
  const [key, dispatch] = useReducer(keyReducer, CLOSED);
  // the key passes from the request to the dialog through this ref and is cleared as it is handed over, so it is never in React state
  // while the proof dialog is open
  const answer = useRef<string | null>(null);
  const [missing, setMissing] = useState(false);

  async function run(proof: Proof) {
    const res = await api.post(`/devices/${deviceId}/rotate-key`, proof);
    answer.current = keyFromAnswer(res.data);
  }

  function done() {
    setAsking(false);
    const k = answer.current;
    answer.current = null;
    if (k) {
      setMissing(false);
      dispatch({ type: 'show', key: k });
    } else {
      setMissing(true);
    }
  }

  return (
    <div className="mt-5 border-t border-surface-200 pt-4 dark:border-surface-800">
      <h3 className="text-base font-semibold text-surface-900 dark:text-surface-50">API key</h3>
      <p className="mt-1 max-w-[72ch] text-base text-surface-800 dark:text-surface-200">
        The key is not stored where it can be read, so it cannot be shown again. If the node&apos;s key is lost or may be known to someone else, replace it. The old key stops working at once.
      </p>
      <div className="mt-3">
        <Button variant="secondary" onClick={() => setAsking(true)}>Replace API key</Button>
      </div>
      {missing && <p role="alert" className="mt-3 text-base font-medium text-critical-800 dark:text-critical-300">The key was replaced but the answer did not carry the new key. Replace it again to get one.</p>}

      <ProofDialog
        open={asking}
        title={`Replace the key for ${machineName}?`}
        confirmLabel="Replace key"
        onCancel={() => setAsking(false)}
        run={run}
        onDone={done}
        returnTo={`/devices/${deviceId}`}
      >
        <p>The old key stops working at once, so the node cannot post until its firmware has the new key. The new key is shown once.</p>
      </ProofDialog>

      <KeyOnceDialog state={key} dispatch={dispatch} machineName={machineName} rotated />
    </div>
  );
}
