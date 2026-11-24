'use client';

import { useState } from 'react';
import api from '@/lib/api';
import type { ApiResource } from '@/hooks/useApiResource';
import Button from '@/components/ui/Button';
import ErrorNotice from '@/components/ui/ErrorNotice';
import Panel from '@/components/ui/Panel';
import ProofDialog, { type Proof } from '@/components/ui/ProofDialog';
import { SkeletonRows } from '@/components/ui/Skeleton';
import Time from '@/components/ui/Time';
import { roleWord } from '@/lib/format';

interface Invitation {
  id: string;
  email: string;
  role: string;
  invited_by_name: string | null;
  created_at: string;
  expires_at: string;
}

// the invitations that can still be used (GET /invitations: not used, not cancelled, not expired). Cancelling one needs the admin's
// fresh proof (DELETE /invitations/{id}); a cancelled link answers "expired" and can no longer be accepted.
export default function Invitations({ resource }: { resource: ApiResource<unknown[]> }) {
  const list = (resource.data ?? []) as Invitation[];
  const [cancelling, setCancelling] = useState<Invitation | null>(null);
  const [notice, setNotice] = useState('');

  async function run(proof: Proof) {
    if (!cancelling) return;
    try {
      await api.delete(`/invitations/${cancelling.id}`, { data: proof });
    } catch (err) {
      // an invitation that is no longer pending answers 404: it is gone, which is what was wanted
      if ((err as { response?: { status?: number } }).response?.status !== 404) throw err;
    }
  }

  return (
    <Panel title="Pending invitations" description="Invitations that have not been used, cancelled or run out. Each lasts 48 hours.">
      <div role="status" className="mb-2 text-base text-surface-900 empty:hidden dark:text-surface-50">{notice}</div>
      {resource.loading && !resource.data ? (
        <SkeletonRows rows={2} label="Loading invitations" />
      ) : resource.error && !resource.data ? (
        <ErrorNotice message={resource.error} onRetry={resource.retry} />
      ) : list.length === 0 ? (
        <p className="text-base text-surface-700 dark:text-surface-300">No invitations are waiting.</p>
      ) : (
        <ul className="divide-y divide-surface-200 border-y border-surface-200 dark:divide-surface-800 dark:border-surface-800">
          {list.map((inv) => (
            <li key={inv.id} className="flex min-h-[56px] flex-wrap items-center justify-between gap-x-4 gap-y-2 py-3">
              <div className="min-w-0">
                <p className="break-all text-base font-medium text-surface-900 dark:text-surface-50">{inv.email} <span className="font-normal text-surface-700 dark:text-surface-300">{roleWord(inv.role)}</span></p>
                <p className="text-base text-surface-600 dark:text-surface-400">
                  {inv.invited_by_name ? `Invited by ${inv.invited_by_name}. ` : ''}Runs out <Time value={inv.expires_at} format="datetime" />.
                </p>
              </div>
              <Button variant="secondary" size="small" onClick={() => { setNotice(''); setCancelling(inv); }} aria-label={`Cancel the invitation for ${inv.email}`}>Cancel invitation</Button>
            </li>
          ))}
        </ul>
      )}
      <ProofDialog
        open={cancelling !== null}
        title="Cancel this invitation?"
        confirmLabel="Cancel invitation"
        destructive
        onCancel={() => setCancelling(null)}
        run={run}
        onDone={() => { setNotice(`The invitation for ${cancelling?.email ?? 'that address'} is cancelled.`); setCancelling(null); resource.retry(); }}
        returnTo="/admin"
      >
        <p>{cancelling?.email} will not be able to use the link they were sent.</p>
      </ProofDialog>
    </Panel>
  );
}
