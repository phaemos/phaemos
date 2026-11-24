'use client';

import { Suspense, use, useCallback, useEffect, useMemo, useState } from 'react';
import api from '@/lib/api';
import { describeApiError } from '@/lib/apiError';
import type { Alert, Device, MlStatus, Telemetry } from '@/types';
import { useApiResource } from '@/hooks/useApiResource';
import { useRole } from '@/hooks/useRole';
import { useOwnerContext } from '@/hooks/useOwnerContext';
import { useToast } from '@/hooks/useToast';
import TelemetryChart from '@/components/TelemetryChart';
import BackLink from '@/components/ui/BackLink';
import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import ConfirmDialog from '@/components/ui/ConfirmDialog';
import ErrorNotice from '@/components/ui/ErrorNotice';
import { Input, Select } from '@/components/ui/Input';
import PageHeader from '@/components/ui/PageHeader';
import Panel from '@/components/ui/Panel';
import { Skeleton, SkeletonGroup, SkeletonRows } from '@/components/ui/Skeleton';
import { useUrlParam } from '@/hooks/useUrlParam';
import type { Range } from '@/lib/telemetryRange';
import ExportCsvButton from '@/components/machines/ExportCsvButton';
import LatestReadings from '@/components/machines/LatestReadings';
import ReadingHistory from '@/components/machines/ReadingHistory';
import MonitoringHealth from '@/components/machines/MonitoringHealth';
import NotFittedControl from '@/components/machines/NotFittedControl';
import ModelBadge from '@/components/machines/ModelBadge';
import RotateKeyControl from '@/components/machines/RotateKeyControl';
import AlertRow from '@/components/alerts/AlertRow';
import EmptyState from '@/components/ui/EmptyState';
import { applyReadings, sortAlerts, uniqueById } from '@/lib/alertLife';
import IntervalControl from '@/components/machines/IntervalControl';
import { AlertsGapProvider } from '@/components/machines/AlertsGap';
import { alertsGap } from '@/lib/machineState';
import { LastPost, LinkBadge, MachineBadge } from '@/components/machines/MachineStatus';
import { nodeTypeLabel } from '@/lib/nodeTypes';
import { ownerLabel } from '@/lib/machineList';
import CopyValue from '@/components/ui/CopyValue';
import { cn } from '@/lib/cn';
import { roleWord } from '@/lib/format';

// the most alerts one read asks for. The API allows 500.
const ALERT_LIMIT = 500;
const RANGE_VALUES = ['1h', '6h', '24h', '7d'] as const;

interface PageProps {
  params: Promise<{ id: string }>;
}

// one term and its value in the details list
function Term({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn('min-w-0', className)}>
      <dt className="label text-surface-700 dark:text-surface-300">{label}</dt>
      <dd className="mt-1 text-base text-surface-900 dark:text-surface-50">{children}</dd>
    </div>
  );
}

// the time range lives in the address, which a page can only read inside a Suspense boundary
export default function MachinePage({ params }: PageProps) {
  return (
    <Suspense fallback={<SkeletonRows rows={6} label="Loading the machine" />}>
      <MachineView params={params} />
    </Suspense>
  );
}

function MachineView({ params }: PageProps) {
  const { id } = use(params);
  const [range, setRange] = useUrlParam<Range>('range', '1h', RANGE_VALUES);
  // readings pushed over the socket, newest first. They reach the latest readings table and the health section at once and are
  // dropped from here when the next poll holds them.
  const [pushed, setPushed] = useState<{ id: string; rows: Telemetry[] }>({ id, rows: [] });
  const onReading = useCallback((r: Telemetry) => setPushed((p) => ({ id, rows: [r, ...(p.id === id ? p.rows : [])].slice(0, 30) })), [id]);
  const role = useRole();
  const isAdmin = role === 'admin';
  const { addToast } = useToast();

  const { data, error, loading, retry } = useApiResource<Device>(`/devices/${id}`, { what: 'The machine', intervalMs: 15000 });
  // a failed refresh keeps the last answer on screen, so the page says so and the reader does not trust a stale state
  const owners = useOwnerContext(isAdmin, role !== null);
  // the newest readings are loaded once and shared by the monitoring health section and the latest readings table
  const readings = useApiResource<Telemetry[]>(`/telemetry/${id}`, { params: { limit: 30 }, what: 'The latest readings', intervalMs: 5000 });
  // the polled readings with any pushed since, once each. A pushed reading older than the newest polled one is already in the poll.
  const merged = useMemo(() => {
    if (!readings.data) return readings;
    const have = new Set(readings.data.map((r) => r.id));
    const newest = readings.data[0] ? Date.parse(readings.data[0].recorded_at) : 0;
    const fresh = (pushed.id === id ? pushed.rows : []).filter((r) => !have.has(r.id) && Date.parse(r.recorded_at) >= newest);
    return fresh.length ? { ...readings, data: [...fresh, ...readings.data] } : readings;
  }, [readings, pushed, id]);

  // this machine's own alerts, newest first. The route takes limit and offset and says in X-Total-Count how many the machine has,
  // so a machine whose critical alert is older than another machine's hundred newer ones is still read correctly. When the
  // machine holds more than the page asked for or the read failed, its state is Unknown and says why.
  const alertsRes = useApiResource<Alert[]>('/alerts', { params: { device_id: id, resolved: false, limit: ALERT_LIMIT }, what: 'The alerts', intervalMs: 15000 });
  const gap = alertsGap(alertsRes);
  // the open alerts of this machine, one row each. A reading pushed over the socket is laid onto the alert it belongs to, in place, so the
  // count, the peak and the latest value move at once and no row is ever added for a reading. The next poll replaces them.
  const openAlerts = useMemo(() => {
    const open = uniqueById(alertsRes.data ?? []).filter((a) => !a.resolved);
    return sortAlerts(applyReadings(open, pushed.id === id ? pushed.rows : []));
  }, [alertsRes.data, pushed, id]);
  const deviceAlerts = useMemo(() => openAlerts.filter((a) => (a.category ?? 'machine') === 'machine'), [openAlerts]);
  // the model's state names a refusal when the last retrain refused this machine's model. The page works without it.
  const ml = useApiResource<MlStatus>('/ml/status', { what: 'The model status', intervalMs: 60_000 });

  // the two fields this page can change are laid over the polled machine, so a poll never undoes a save
  const [patch, setPatch] = useState<{ id: string; owner_id?: string | null; tags?: string[]; not_fitted?: string[]; expected_interval_s?: number } | null>(null);
  const device = useMemo<Device | null>(() => (data ? { ...data, ...(patch && patch.id === data.id ? patch : {}) } : null), [data, patch]);

  const [savingOwner, setSavingOwner] = useState(false);
  const [newTag, setNewTag] = useState('');
  const [tagError, setTagError] = useState<string | undefined>();
  const [savingTag, setSavingTag] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);
  const [removingPending, setRemovingPending] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  // the tab names the machine. A client page cannot export metadata, so the title is set here once the name is known.
  const machineName = data?.name;
  useEffect(() => {
    if (machineName) document.title = `${machineName} | PHAEMOS`;
  }, [machineName]);

  // a link from a sensor alert ends in #monitoring-health. The section exists only once the machine has loaded, so the browser's
  // own jump finds nothing and the page scrolls there itself.
  const loaded = Boolean(data);
  useEffect(() => {
    if (loaded && window.location.hash === '#monitoring-health') document.getElementById('monitoring-health')?.scrollIntoView();
  }, [loaded]);

  if (loading) {
    return (
      <div className="space-y-6">
        <BackLink href="/devices">machines</BackLink>
        <SkeletonGroup label="Loading the machine" className="space-y-4">
          <Skeleton className="h-7 w-64" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-64 w-full" />
        </SkeletonGroup>
      </div>
    );
  }

  if (!device) {
    return (
      <div className="space-y-4">
        <BackLink href="/devices">machines</BackLink>
        <h1 className="text-xl font-semibold tracking-tight text-surface-900 dark:text-surface-50">Machine</h1>
        <ErrorNotice message={error ?? 'The machine did not load.'} onRetry={retry} />
      </div>
    );
  }

  const tags = device.tags ?? [];

  async function changeOwner(ownerId: string) {
    setSavingOwner(true);
    try {
      const res = await api.patch<Device>(`/devices/${id}`, { owner_id: ownerId || null });
      setPatch((p) => ({ ...(p && p.id === id ? p : { id }), owner_id: res.data.owner_id }));
      addToast('success', 'Owner updated.');
    } catch (err) {
      addToast('error', `The owner was not changed. ${describeApiError(err, 'The machine')}`);
    } finally {
      setSavingOwner(false);
    }
  }

  async function addTag() {
    const tag = newTag.trim().toLowerCase().replace(/\s+/g, '-');
    if (!tag) {
      setTagError('Enter a tag.');
      return;
    }
    if (tags.includes(tag)) {
      setTagError('This machine already has that tag.');
      return;
    }
    setTagError(undefined);
    setSavingTag(true);
    try {
      const res = await api.post<Device>(`/devices/${id}/tags`, { tag });
      setPatch((p) => ({ ...(p && p.id === id ? p : { id }), tags: res.data.tags ?? [] }));
      setNewTag('');
    } catch (err) {
      setTagError(`The tag was not added. ${describeApiError(err, 'The machine')}`);
    } finally {
      setSavingTag(false);
    }
  }

  async function removeTag() {
    if (!removing) return;
    setRemovingPending(true);
    try {
      const res = await api.delete<Device>(`/devices/${id}/tags/${encodeURIComponent(removing)}`);
      setPatch((p) => ({ ...(p && p.id === id ? p : { id }), tags: res.data.tags ?? [] }));
      setRemoving(null);
    } catch (err) {
      addToast('error', `The tag was not removed. ${describeApiError(err, 'The machine')}`);
      setRemoving(null);
    } finally {
      setRemovingPending(false);
    }
  }

  return (
    <AlertsGapProvider gap={gap}>
    <div className="space-y-6">
      <div className="space-y-1">
        <BackLink href="/devices">machines</BackLink>
        <PageHeader title={device.name} actions={<ExportCsvButton deviceId={id} name={device.name} onError={setExportError} />} />
      </div>

      {exportError && <ErrorNotice message={exportError} />}
      {error && data && <ErrorNotice message="This page could not be refreshed. The state and readings shown may be out of date." detail={error} onRetry={retry} />}
      {gap && (alertsRes.error || alertsRes.data) && <ErrorNotice message="This machine's state is Unknown." detail={`That is because ${gap}. It is not called healthy while its alerts are unknown.`} onRetry={alertsRes.retry} />}

      <Panel title="Details" bodyClassName="p-4">
        <dl className="grid grid-cols-[minmax(0,1fr)] gap-x-8 gap-y-5 sm:grid-cols-2 lg:grid-cols-4">
          <Term label="Machine state"><MachineBadge device={device} alerts={deviceAlerts} /></Term>
          <Term label="Monitoring link">
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <LinkBadge device={device} />
              <span className="text-sm text-surface-700 dark:text-surface-300">last post: <LastPost device={device} showExact /></span>
            </span>
          </Term>
          <Term label="Anomaly model" className="sm:col-span-2"><ModelBadge device={device} status={ml.data} detail /></Term>
          <Term label="Node type">{nodeTypeLabel(device.type)}</Term>
          <Term label="Location">{device.location ?? <span className="text-surface-600 dark:text-surface-400">No location</span>}</Term>
          <Term label="Owner">
            {isAdmin ? (
              <Select
                label="Change owner"
                value={device.owner_id ?? ''}
                onChange={(e) => changeOwner(e.target.value)}
                disabled={savingOwner || !owners.ready}
                wrapperClassName="max-w-xs [&_label]:sr-only"
              >
                <option value="">Unassigned</option>
                {owners.users.map((u) => <option key={u.id} value={u.id}>{u.name ?? u.email} ({roleWord(u.role)})</option>)}
              </Select>
            ) : !device.owner_id ? (
              'Unassigned'
            ) : owners.ready ? (
              ownerLabel(device.owner_id, owners)
            ) : (
              <span className="text-surface-600 dark:text-surface-400">Loading</span>
            )}
          </Term>
          <Term label="Machine ID" className="sm:col-span-2"><CopyValue value={device.id} what="machine ID" /></Term>
          <div className="min-w-0 sm:col-span-2">
            <dt className="label text-surface-700 dark:text-surface-300">Tags</dt>
            <dd className="mt-1 text-base text-surface-900 dark:text-surface-50">
              {tags.length === 0 ? (
                <span className="text-surface-600 dark:text-surface-400">No tags</span>
              ) : (
                <ul className="flex flex-wrap items-center gap-2">
                  {tags.map((t) => (
                    <li key={t} className="flex items-center gap-1">
                      <Badge>{t}</Badge>
                      {isAdmin && <Button variant="ghost" size="small" aria-label={`Remove tag ${t}`} onClick={() => setRemoving(t)}>Remove</Button>}
                    </li>
                  ))}
                </ul>
              )}
            </dd>
          </div>
        </dl>

        {isAdmin && (
          <form
            className="mt-5 flex max-w-md flex-wrap items-start gap-3 border-t border-surface-200 pt-4 dark:border-surface-800"
            onSubmit={(e) => { e.preventDefault(); addTag(); }}
          >
            <Input label="Add a tag" value={newTag} onChange={(e) => setNewTag(e.target.value)} error={tagError} wrapperClassName="min-w-48 flex-1" autoComplete="off" />
            <Button type="submit" variant="secondary" pending={savingTag} className="mt-[26px]">Add tag</Button>
          </form>
        )}

        {(isAdmin || (owners.me !== null && owners.me !== undefined && device.owner_id === owners.me.id)) && (
          <RotateKeyControl deviceId={id} machineName={device.name} />
        )}

        {isAdmin && (
          <IntervalControl
            deviceId={id}
            current={device.expected_interval_s ?? 5}
            onSaved={(expected_interval_s) => setPatch((p) => ({ ...(p && p.id === id ? p : { id }), expected_interval_s }))}
          />
        )}
      </Panel>

      <Panel
        id="machine-alerts"
        title="Active alerts"
        description="Each alert lasts as long as its condition and updates in place as readings arrive."
        bodyClassName="p-0"
      >
        {alertsRes.error && !alertsRes.data ? (
          <div className="p-4"><ErrorNotice message={alertsRes.error} detail="This is not the same as no alerts." onRetry={alertsRes.retry} pending={alertsRes.loading} /></div>
        ) : !alertsRes.data ? (
          <div className="p-4"><SkeletonRows rows={2} label="Loading alerts" /></div>
        ) : openAlerts.length === 0 ? (
          <EmptyState heading="No active alerts" subMessage="No rule has been broken and the model has not flagged this machine." />
        ) : (
          <ul className="divide-y divide-surface-200 dark:divide-surface-800">
            {openAlerts.map((a) => (
              <AlertRow key={a.id} alert={a} name={device.name} hideMachine />
            ))}
          </ul>
        )}
      </Panel>

      <MonitoringHealth device={device} readings={merged.data ?? []} isAdmin={isAdmin} onCounterAccepted={() => { addToast('success', 'A new counter was accepted. The machine\'s next post sets the new start.'); retry(); }}>
        {isAdmin && (
          <NotFittedControl
            deviceId={id}
            current={device.not_fitted ?? []}
            onSaved={(not_fitted) => setPatch((p) => ({ ...(p && p.id === id ? p : { id }), not_fitted }))}
          />
        )}
      </MonitoringHealth>

      <TelemetryChart deviceId={id} device={device} range={range} onRangeChange={setRange} onReading={onReading} />

      <LatestReadings device={device} readings={merged} />

      <ReadingHistory deviceId={id} />

      <ConfirmDialog
        open={removing !== null}
        title="Remove tag"
        confirmLabel="Remove tag"
        pending={removingPending}
        onCancel={() => setRemoving(null)}
        onConfirm={removeTag}
      >
        <p>
          Remove <span className="font-medium">{removing}</span> from {device.name}? A firmware update by this tag will no longer reach this machine. You can add the tag again.
        </p>
      </ConfirmDialog>
    </div>
    </AlertsGapProvider>
  );
}
