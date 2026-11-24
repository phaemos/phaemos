'use client';

import { useState } from 'react';
import api from '@/lib/api';
import { describeApiError } from '@/lib/apiError';
import { requestIdOf } from '@/lib/apiCode';
import RequestRef from '@/components/ui/RequestRef';
import Button from '@/components/ui/Button';
import ConfirmDialog from '@/components/ui/ConfirmDialog';
import StatusBadge, { StatusShape } from '@/components/ui/StatusBadge';
import Time from '@/components/ui/Time';
import { endSentence, replayView } from '@/lib/replay';
import type { ReplayFields } from '@/types/monitoring';

interface Props {
  machineId: string;
  machineName: string;
  device: ReplayFields;
  isAdmin: boolean;
  // called after the API accepted a new counter. The page says so and reads the machine again, which remounts this section.
  onAccepted: () => void;
}

// whether a captured post could be sent again. The sentences are the API's own (`replay_status`, `replay_warning`, `replay_recovery`)
// and are shown as they come. An admin can accept a new counter for a machine whose flash was wiped. That forgets the last boot and
// seq so the next post sets the new start. It does not make the key safe, which the confirmation says plainly.
export default function ReplaySection({ machineId, machineName, device, isAdmin, onAccepted }: Props) {
  const v = replayView(device, isAdmin);
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reference, setReference] = useState<string | null>(null);

  async function accept() {
    setPending(true);
    setError(null);
    try {
      await api.post(`/devices/${machineId}/accept-counter`);
      setOpen(false);
      onAccepted();
    } catch (err) {
      setError(describeApiError(err, 'The machine'));
      setReference(requestIdOf(err) ?? null);
    } finally {
      setPending(false);
    }
  }

  const status = v.protected === null ? 'unknown' : v.protected && !v.lockedOut ? 'healthy' : 'warning';

  return (
    <section aria-labelledby="replay-title">
      <h3 id="replay-title" className="text-base font-semibold text-surface-900 dark:text-surface-50">Replay protection</h3>
      <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-base text-surface-900 dark:text-surface-50">
        <StatusBadge status={status} label={v.label} />
        <span className="max-w-[72ch] text-surface-800 dark:text-surface-200">{endSentence(v.status)}</span>
      </p>
      {v.warning && (
        <p role="status" className="mt-2 flex max-w-[72ch] items-start gap-2 text-base font-medium text-surface-900 dark:text-surface-50">
          <span className="mt-1.5 text-warning-800 dark:text-warning-400"><StatusShape shape="triangle" /></span>
          <span>{endSentence(v.warning)}{device.counter_jump_at ? <> (<Time value={device.counter_jump_at} format="datetime" />)</> : null}</span>
        </p>
      )}
      <dl className="mt-3 grid grid-cols-[minmax(0,1fr)] gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
        {v.lastPair && (
          <div className="min-w-0">
            <dt className="label text-surface-700 dark:text-surface-300">Last post accepted</dt>
            <dd className="mt-1 text-base text-surface-900 dark:text-surface-50"><span className="num">{v.lastPair}</span></dd>
          </div>
        )}
        {v.refused > 0 && (
          <div className="min-w-0">
            <dt className="label text-surface-700 dark:text-surface-300">Posts refused since</dt>
            <dd className="mt-1 text-base text-surface-900 dark:text-surface-50">
              <span className="tnum">{v.refused}</span>
              {v.refusedAt && <span className="block text-sm text-surface-700 dark:text-surface-300">Latest <Time value={v.refusedAt} format="datetime" /></span>}
            </dd>
          </div>
        )}
      </dl>

      {v.canAccept && (
        <div className="mt-3">
          <Button variant="secondary" onClick={() => { setError(null); setOpen(true); }}>Accept a new counter</Button>
        </div>
      )}

      <ConfirmDialog
        open={open}
        title={`Accept a new counter for ${machineName}?`}
        confirmLabel="Accept a new counter"
        destructive={false}
        pending={pending}
        onCancel={() => setOpen(false)}
        onConfirm={accept}
      >
        <div className="space-y-3">
          <p>This forgets the last boot and seq this machine sent, so its next post is taken as the new start. Use it only after the machine&apos;s flash was wiped. The machine must still send both numbers.</p>
          <p>While the old counter stands, every post with a lower one is refused. After this, a post that was captured earlier could be accepted if it is newer than the new start.</p>
          {v.recovery && <p className="font-medium text-surface-900 dark:text-surface-50">{endSentence(v.recovery)}</p>}
          {v.keyAtRisk && <p className="font-medium text-surface-900 dark:text-surface-50">The counter was pushed up. Rotate this machine&apos;s key as well, because someone else may hold it.</p>}
          {error && <><p role="alert" className="font-medium text-critical-800 dark:text-critical-300">{error}</p><RequestRef id={reference} /></>}
        </div>
      </ConfirmDialog>
    </section>
  );
}
