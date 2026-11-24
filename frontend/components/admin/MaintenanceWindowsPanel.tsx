'use client';

import { lookup } from '@/lib/lookup';
import { useMemo, useState } from 'react';
import api from '@/lib/api';
import type { Device } from '@/types';
import { useApiResource } from '@/hooks/useApiResource';
import { apiDetail } from '@/lib/apiDetail';
import { describeApiError } from '@/lib/apiError';
import { formatDateTime } from '@/lib/format';
import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import Checkbox from '@/components/ui/Checkbox';
import ConfirmDialog from '@/components/ui/ConfirmDialog';
import DataTable from '@/components/ui/DataTable';
import EmptyState from '@/components/ui/EmptyState';
import ErrorNotice from '@/components/ui/ErrorNotice';
import { Input, Select } from '@/components/ui/Input';
import Panel from '@/components/ui/Panel';
import { SkeletonRows } from '@/components/ui/Skeleton';
import Time from '@/components/ui/Time';
import RequestRef from '@/components/ui/RequestRef';
import { useIdempotencyKey } from '@/hooks/useIdempotencyKey';
import { idempotent } from '@/lib/idempotency';
import { errorInfo } from '@/lib/apiCode';
import Pager from './Pager';

interface MaintenanceWindow {
  id: string;
  label: string;
  start_at: string;
  end_at: string;
  device_id: string | null;
  suppress_alerts: boolean;
}

function isActive(w: MaintenanceWindow) {
  const now = Date.now();
  return new Date(w.start_at).getTime() <= now && new Date(w.end_at).getTime() >= now;
}

// the list is paged at 50 by default
const PAGE_SIZE = 50;

export default function MaintenanceWindowsPanel() {
  const [skip, setSkip] = useState(0);
  const windows = useApiResource<MaintenanceWindow[]>('/maintenance-windows', { params: { limit: PAGE_SIZE, offset: skip }, what: 'The maintenance windows' });
  const idem = useIdempotencyKey();
  const [reference, setReference] = useState<string | null>(null);
  const machines = useApiResource<Device[]>('/devices', { params: { limit: 200 }, what: 'The machines' });
  const names = useMemo(() => Object.fromEntries((machines.data ?? []).map((d) => [d.id, d.name])), [machines.data]);

  const [label, setLabel] = useState('');
  const [machine, setMachine] = useState('');
  const [startAt, setStartAt] = useState('');
  const [endAt, setEndAt] = useState('');
  const [suppress, setSuppress] = useState(true);
  const [errors, setErrors] = useState<{ label?: string; start?: string; end?: string }>({});
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);

  const [toDelete, setToDelete] = useState<MaintenanceWindow | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setFormError('');
    const next: typeof errors = {};
    if (!label.trim()) next.label = 'Enter a label.';
    if (!startAt) next.start = 'Choose a start.';
    if (!endAt) next.end = 'Choose an end.';
    else if (startAt && new Date(endAt) <= new Date(startAt)) next.end = 'End must be after start.';
    setErrors(next);
    if (Object.keys(next).length) return;
    setSaving(true);
    setReference(null);
    try {
      const body = {
        label: label.trim(),
        start_at: new Date(startAt).toISOString(),
        end_at: new Date(endAt).toISOString(),
        suppress_alerts: suppress,
        // left out for every machine, which is what the API does without it
        ...(machine ? { device_id: machine } : {}),
      };
      // one Idempotency-Key for this submission: a double click or a retry after a time-out gets the first answer back and makes no second window
      await api.post('/maintenance-windows', body, idempotent(idem.keyFor(JSON.stringify(body))));
      idem.renew();
      setLabel('');
      setMachine('');
      setStartAt('');
      setEndAt('');
      setSuppress(true);
      setSkip(0);
      windows.retry();
    } catch (err) {
      setFormError(apiDetail(err) ?? describeApiError(err, 'The window'));
      setReference(errorInfo(err).requestId ?? null);
    } finally {
      setSaving(false);
    }
  }

  async function confirmDelete() {
    if (!toDelete) return;
    setDeleting(true);
    setDeleteError('');
    try {
      await api.delete(`/maintenance-windows/${toDelete.id}`);
      setToDelete(null);
      if (windows.data && windows.data.length === 1 && skip > 0) setSkip(Math.max(0, skip - PAGE_SIZE));
      windows.retry();
    } catch (err) {
      setDeleteError(describeApiError(err, 'The window'));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="space-y-6">
      <Panel title="Schedule a window" description="While a window is open and set to suppress alerts we do not raise alerts for the machine it covers.">
        <form onSubmit={create} noValidate className="max-w-xl space-y-4">
          <Input label="Label" required value={label} onChange={(e) => setLabel(e.target.value)} error={errors.label} hint="For example Firmware upgrade, node 3" wrapperClassName="min-h-[124px]" />
          <Select label="Machine" value={machine} onChange={(e) => setMachine(e.target.value)} hint={machines.error ?? undefined}>
            <option value="">All machines</option>
            {(machines.data ?? []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </Select>
          <div className="grid gap-4 sm:grid-cols-2">
            <Input label="Start" required type="datetime-local" value={startAt} onChange={(e) => setStartAt(e.target.value)} error={errors.start} wrapperClassName="min-h-[100px]" />
            <Input label="End" required type="datetime-local" value={endAt} onChange={(e) => setEndAt(e.target.value)} error={errors.end} wrapperClassName="min-h-[100px]" />
          </div>
          <Checkbox label="Suppress alerts during this window" checked={suppress} onChange={(e) => setSuppress(e.target.checked)} />
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" pending={saving}>Schedule window</Button>
            <p role="alert" className="min-h-5 text-base font-medium text-critical-800 dark:text-critical-300">{formError}</p>
            {formError && <RequestRef id={reference} />}
          </div>
        </form>
      </Panel>

      <Panel title="Windows" bodyClassName="p-0">
        {windows.loading && !windows.data ? (
          <div className="p-4"><SkeletonRows rows={3} label="Loading maintenance windows" /></div>
        ) : windows.error && !windows.data ? (
          <div className="p-4"><ErrorNotice message={windows.error} onRetry={windows.retry} /></div>
        ) : windows.data && windows.data.length === 0 && skip === 0 ? (
          <EmptyState heading="No maintenance windows" subMessage="Schedule one above before planned work so it does not raise alerts." />
        ) : windows.data ? (
          <>
            {windows.error && <div className="p-4"><ErrorNotice message={windows.error} onRetry={windows.retry} /></div>}
            <DataTable caption="Maintenance windows">
              <thead>
                <tr>
                  <th scope="col">Label</th>
                  <th scope="col">Machine</th>
                  <th scope="col">Starts</th>
                  <th scope="col">Ends</th>
                  <th scope="col">Alerts</th>
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {windows.data.map((w) => (
                  <tr key={w.id}>
                    <td>
                      {w.label}
                      {isActive(w) && <Badge tone="warning" shape className="ml-2">Open now</Badge>}
                    </td>
                    <td>{w.device_id ? lookup(names, w.device_id) ?? 'Unknown machine' : 'All machines'}</td>
                    <td className="whitespace-nowrap"><Time value={w.start_at} /></td>
                    <td className="whitespace-nowrap"><Time value={w.end_at} /></td>
                    <td>{w.suppress_alerts ? 'Off' : 'Still on'}</td>
                    <td>
                      <div className="flex justify-end">
                        <Button size="small" variant="secondary" onClick={() => { setDeleteError(''); setToDelete(w); }} aria-label={`Delete ${w.label}`}>Delete</Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
            <Pager skip={skip} shown={windows.data.length} pageSize={PAGE_SIZE} total={windows.total} onChange={setSkip} what="Maintenance windows" />
          </>
        ) : null}
      </Panel>

      <ConfirmDialog open={toDelete !== null} title="Delete this maintenance window?" confirmLabel="Delete window" onCancel={() => setToDelete(null)} onConfirm={confirmDelete} pending={deleting}>
        {toDelete && (
          <>
            <p>
              {toDelete.label}, from <Time value={toDelete.start_at} /> to <Time value={toDelete.end_at} />, will be removed.
              {isActive(toDelete) && toDelete.suppress_alerts ? ' It is open now, so alerts start again straight away.' : ''} This cannot be undone.
            </p>
            <p role="alert" className="mt-2 min-h-5 font-medium text-critical-800 dark:text-critical-300">{deleteError}</p>
          </>
        )}
      </ConfirmDialog>
    </div>
  );
}
