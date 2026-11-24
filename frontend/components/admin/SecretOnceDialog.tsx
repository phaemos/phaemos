'use client';

import type { Dispatch } from 'react';
import { useState } from 'react';
import ConfirmDialog from '@/components/ui/ConfirmDialog';
import ErrorNotice from '@/components/ui/ErrorNotice';
import { Input } from '@/components/ui/Input';
import { StatusShape } from '@/components/ui/StatusBadge';
import { CheckIcon, CopyIcon } from '@/components/ui/icons';
import type { KeyAction, KeyOnce } from '@/lib/keyOnce';
import { SECRET_WARNING, SECRET_WARNING_ROTATED, VERIFY_LINK } from '@/lib/webhooks';

interface Props {
  state: KeyOnce;
  dispatch: Dispatch<KeyAction>;
  webhookName: string;
  // true after a rotation: the old secret has stopped signing
  rotated: boolean;
}

// shows a webhook's signing secret once, the same way KeyOnceDialog shows a machine's key: Close, Escape and a click outside all ask first
// and only the confirmation drops the secret from page state (lib/keyOnce.ts holds it and nothing else does). The server keeps it encrypted
// and no route returns it again.
export default function SecretOnceDialog({ state, dispatch, webhookName, rotated }: Props) {
  const [failed, setFailed] = useState(false);
  const shown = state.phase === 'shown';
  const confirming = state.phase === 'confirming';
  const secret = state.phase === 'closed' ? '' : state.key;
  const copied = state.phase !== 'closed' && state.copied;

  async function copy() {
    setFailed(false);
    try {
      await navigator.clipboard.writeText(secret);
      dispatch({ type: 'copied' });
    } catch {
      setFailed(true);
    }
  }

  return (
    <>
      <ConfirmDialog
        open={shown}
        title={rotated ? 'New signing secret' : 'Webhook added'}
        confirmLabel={copied ? 'Copied' : 'Copy signing secret'}
        confirmIcon={copied ? <CheckIcon /> : <CopyIcon />}
        cancelLabel="Close"
        destructive={false}
        onCancel={() => dispatch({ type: 'ask_close' })}
        onConfirm={copy}
      >
        <div className="space-y-4">
          <p>
            <span className="font-medium">{webhookName}</span>
            {rotated ? ' has a new signing secret. Put it in the receiver.' : ' signs every delivery with this secret. Put it in the receiver so it can check each one.'}
          </p>
          <p className="flex items-start gap-2 rounded-md border border-warning-800 px-3 py-2 font-medium text-surface-900 dark:border-warning-400 dark:text-surface-50">
            <span className="mt-1.5 text-warning-800 dark:text-warning-400"><StatusShape shape="triangle" /></span>
            <span>{rotated ? SECRET_WARNING_ROTATED : SECRET_WARNING}</span>
          </p>
          <Input label="Signing secret" readOnly value={secret} onFocus={(e) => e.currentTarget.select()} className="font-mono" autoComplete="off" spellCheck={false} />
          {failed && <ErrorNotice message="The secret could not be copied. Select it and copy it by hand before you close this." />}
          <p aria-live="polite" className="sr-only">{copied ? 'Signing secret copied to the clipboard' : ''}</p>
          <p className="text-base text-surface-800 dark:text-surface-200">
            How a receiver checks a delivery, with an example, is in the <a href={VERIFY_LINK} className="underline underline-offset-2" target="_blank" rel="noopener noreferrer">API reference<span className="sr-only"> (opens in a new tab)</span></a>.
          </p>
        </div>
      </ConfirmDialog>

      <ConfirmDialog
        open={confirming}
        title="Close without the secret?"
        confirmLabel="Close and forget the secret"
        cancelLabel="Go back to the secret"
        onCancel={() => dispatch({ type: 'keep' })}
        onConfirm={() => dispatch({ type: 'close' })}
      >
        <p>
          {copied ? 'You copied the secret.' : 'You have not copied the secret.'} Once this closes it is gone for good: this page cannot show it again and neither can the API. You can make a new one by rotating it, which stops this one working.
        </p>
      </ConfirmDialog>
    </>
  );
}
