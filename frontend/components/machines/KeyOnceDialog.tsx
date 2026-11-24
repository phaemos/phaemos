'use client';

import type { Dispatch } from 'react';
import { useState } from 'react';
import ConfirmDialog from '@/components/ui/ConfirmDialog';
import ErrorNotice from '@/components/ui/ErrorNotice';
import { Input } from '@/components/ui/Input';
import { StatusShape } from '@/components/ui/StatusBadge';
import { CheckIcon, CopyIcon } from '@/components/ui/icons';
import { keyWarning, type KeyAction, type KeyOnce } from '@/lib/keyOnce';

interface Props {
  state: KeyOnce;
  dispatch: Dispatch<KeyAction>;
  machineName: string;
  // true after a replacement: the old key has stopped working
  rotated: boolean;
}

// shows a device key once. The server keeps only a hash of it, so this is the one chance to copy it. The dialog cannot be closed in
// one step: Close, Escape and a click outside all ask first and only the confirmation drops the key from page state. The key is held
// in the parent's reducer (lib/keyOnce.ts) and nowhere else, so a closed dialog holds nothing.
export default function KeyOnceDialog({ state, dispatch, machineName, rotated }: Props) {
  const [failed, setFailed] = useState(false);
  const shown = state.phase === 'shown';
  const confirming = state.phase === 'confirming';
  const key = state.phase === 'closed' ? '' : state.key;
  const copied = state.phase !== 'closed' && state.copied;

  async function copy() {
    setFailed(false);
    try {
      await navigator.clipboard.writeText(key);
      dispatch({ type: 'copied' });
    } catch {
      setFailed(true);
    }
  }

  return (
    <>
      <ConfirmDialog
        open={shown}
        title={rotated ? 'New API key' : 'Machine added'}
        confirmLabel={copied ? 'Copied' : 'Copy API key'}
        confirmIcon={copied ? <CheckIcon /> : <CopyIcon />}
        cancelLabel="Close"
        destructive={false}
        onCancel={() => dispatch({ type: 'ask_close' })}
        onConfirm={copy}
      >
        <div className="space-y-4">
          <p>
            <span className="font-medium">{machineName}</span>
            {rotated ? ' has a new key. Put it in the node’s firmware.' : ' is registered. Its node sends this key with every reading.'}
          </p>
          <p className="flex items-start gap-2 rounded-md border border-warning-800 px-3 py-2 font-medium text-surface-900 dark:border-warning-400 dark:text-surface-50">
            <span className="mt-1.5 text-warning-800 dark:text-warning-400"><StatusShape shape="triangle" /></span>
            <span>{keyWarning(rotated)}</span>
          </p>
          <Input label="API key" readOnly value={key} onFocus={(e) => e.currentTarget.select()} className="font-mono" autoComplete="off" spellCheck={false} />
          {failed && <ErrorNotice message="The key could not be copied. Select it and copy it by hand before you close this." />}
          <p aria-live="polite" className="sr-only">{copied ? 'API key copied to the clipboard' : ''}</p>
        </div>
      </ConfirmDialog>

      <ConfirmDialog
        open={confirming}
        title="Close without the key?"
        confirmLabel="Close and forget the key"
        cancelLabel="Go back to the key"
        onCancel={() => dispatch({ type: 'keep' })}
        onConfirm={() => dispatch({ type: 'close' })}
      >
        <p>
          {copied ? 'You copied the key.' : 'You have not copied the key.'} Once this closes it is gone for good: this page cannot show it again and neither can the API.
          {rotated ? ' The old key no longer works, so the node stays cut off until a new key is in its firmware.' : ' You can replace the key later, which makes a new one.'}
        </p>
      </ConfirmDialog>
    </>
  );
}
