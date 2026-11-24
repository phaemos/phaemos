'use client';

import { useCallback, useMemo, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import api from '@/lib/api';
import { describeApiError } from '@/lib/apiError';
import { useRole } from '@/hooks/useRole';
import { canWrite as canWriteRole } from '@/lib/role';
import ReadOnlyNote from '@/components/ui/ReadOnlyNote';
import FilterDisclosure from '@/components/ui/FilterDisclosure';
import { useApiResource } from '@/hooks/useApiResource';
import { useKeysetList } from '@/hooks/useKeysetList';
import { requestIdOf } from '@/lib/apiCode';
import type { Alert, Device } from '@/types';
import Button from '@/components/ui/Button';
import ConfirmDialog from '@/components/ui/ConfirmDialog';
import EmptyState from '@/components/ui/EmptyState';
import ErrorNotice from '@/components/ui/ErrorNotice';
import PageHeader from '@/components/ui/PageHeader';
import Panel from '@/components/ui/Panel';
import Segmented from '@/components/ui/Segmented';
import { Select } from '@/components/ui/Input';
import { SkeletonRows } from '@/components/ui/Skeleton';
import { activeFilterCount, alertFiltersToQuery, ALERT_KINDS, hasNarrowingFilters, KIND_WORDS, parseAlertFilters, DEFAULT_ALERT_FILTERS, type AlertFilters } from '@/lib/alertFilters';
import { parseAlertMessage } from '@/lib/alertGroups';
import { isModelAlert, uniqueById } from '@/lib/alertLife';
import { formatDateTime, plural } from '@/lib/format';
import AlertList from './AlertList';
import NotificationLimitNotice from './NotificationLimitNotice';
import CriticalNow from './CriticalNow';
import Time from '@/components/ui/Time';

const REFRESH_MS = 10_000;
// the most machines one request asks for. The API default is 20, which would leave names missing on a larger fleet.
const DEVICE_LIMIT = 200;
// the alerts are read in pages of this many by keyset paging: the page asks for the older ones with `before` until one comes back short;
// the filters are asked of the server, because filtering one page here would be wrong once there are more alerts than a page holds.
const PAGE = 50;

const STATES = [
  { value: 'active', label: 'Active' },
  { value: 'resolved', label: 'Resolved' },
] as const;

export default function AlertsView() {
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const filters = useMemo(() => parseAlertFilters(search), [search]);
  const query = alertFiltersToQuery(filters);
  const role = useRole();
  // until the role is known no write control is offered, so a viewer never sees one flash
  const canWrite = canWriteRole(role);

  const setFilters = useCallback(
    (patch: Partial<AlertFilters>) => {
      const next = alertFiltersToQuery({ ...filters, ...patch });
      router.replace(next ? `${pathname}?${next}` : pathname, { scroll: false });
    },
    [filters, pathname, router],
  );

  // the list polls its first page while the tab is visible and stops while it is hidden, then fetches at once on return. State, About,
  // severity and machine are asked of the server.
  const alerts = useKeysetList<Alert>('/alerts', {
    params: {
      resolved: filters.state === 'resolved',
      category: filters.category === 'all' ? undefined : filters.category,
      severity: filters.severity === 'all' ? undefined : filters.severity,
      kind: filters.kind === 'all' ? undefined : filters.kind,
      device_id: filters.machine || undefined,
    },
    pageSize: PAGE,
    cursorOf: (a) => `${a.triggered_at},${a.id}`,
    intervalMs: REFRESH_MS,
    what: 'The alerts',
  });
  const machines = useApiResource<Device[]>('/devices', { params: { limit: DEVICE_LIMIT }, what: 'The machine names' });

  // the time of the last answer that succeeded. A failed poll keeps the old list and the old time.
  const updatedAt = alerts.updatedAt;
  const hasData = alerts.updatedAt !== null;

  const [pendingIds, setPendingIds] = useState<ReadonlySet<string>>(new Set());
  // resolved a moment ago and not yet gone from the next answer, so the row leaves at once
  const [gone, setGone] = useState<ReadonlySet<string>>(new Set());
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<{ text: string; ref: string | null } | null>(null);
  // an alert whose condition is still occurring is raised again after a hand resolve, so that one asks first
  const [confirm, setConfirm] = useState<Alert | null>(null);

  const deviceNames = useMemo(() => Object.fromEntries((machines.data ?? []).map((d) => [d.id, d.name])), [machines.data]);
  // the name inside the alert text covers a machine this account cannot list
  const fallbackNames = useMemo(() => {
    const out: Record<string, string> = {};
    for (const a of alerts.items) {
      const name = parseAlertMessage(a.message)?.deviceName;
      if (name && !out[a.device_id]) out[a.device_id] = name;
    }
    return out;
  }, [alerts.items]);
  const nameOf = (id: string) => deviceNames[id] ?? fallbackNames[id] ?? 'Unknown machine';

  // one row for each alert id: a poll and a resolve can overlap and an alert is never drawn twice. The order is the server's: newest raised first.
  const matching = useMemo(() => uniqueById(alerts.items).filter((a) => !gone.has(a.id)), [alerts.items, gone]);

  // every machine the account can list, so the filter offers a machine whose alerts are not on the page yet
  const machineOptions = useMemo(() => {
    const names = new Map<string, string>(Object.entries(fallbackNames));
    for (const d of machines.data ?? []) names.set(d.id, d.name);
    if (filters.machine && !names.has(filters.machine)) names.set(filters.machine, 'Unknown machine');
    return [...names].map(([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name));
  }, [machines.data, filters.machine, fallbackNames]);

  const resolveIds = useCallback(
    async (ids: string[]) => {
      setActionError(null);
      setNotice(null);
      setPendingIds((prev) => new Set([...prev, ...ids]));
      const results = await Promise.allSettled(ids.map((id) => api.post(`/alerts/${id}/resolve`)));
      const ok = ids.filter((_, i) => results[i].status === 'fulfilled');
      const failed = results.find((r): r is PromiseRejectedResult => r.status === 'rejected');
      setPendingIds((prev) => new Set([...prev].filter((id) => !ids.includes(id))));
      if (ok.length) {
        setGone((prev) => new Set([...prev, ...ok]));
        setNotice(`Resolved ${ok.length} ${ok.length === 1 ? 'alert' : 'alerts'}.`);
      }
      if (failed) {
        const some = ok.length ? ` ${ids.length - ok.length} of ${ids.length} were not resolved.` : '';
        setActionError({ text: `${describeApiError(failed.reason, 'The alert')}${some}`, ref: requestIdOf(failed.reason) ?? null });
      }
      alerts.retry();
    },
    [alerts],
  );

  const available = matching.length;
  const stateWord = filters.state === 'active' ? 'Active alerts' : 'Resolved alerts';
  const summary = alerts.hasMore ? `${plural(available, 'alert')} so far` : plural(available, 'alert');
  const modelCount = matching.filter((a) => isModelAlert(a)).length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Alerts"
        description="An alert lasts as long as its condition: one open alert for each machine and rule, updated as readings arrive. The newest come first. Alerts about monitoring say that a sensor or a node is not working."
      />

      <NotificationLimitNotice isAdmin={role === 'admin'} />

      {role === 'viewer' && <ReadOnlyNote>You can read every alert here. Resolving an alert and creating a ticket from one are for technicians and admins.</ReadOnlyNote>}

      <CriticalNow severity={filters.severity} state={filters.state} onChoose={(severity) => setFilters({ severity, state: 'active' })} />

      <FilterDisclosure count={activeFilterCount(filters)}>
      <div role="group" aria-label="Filter alerts" className="flex flex-wrap items-end gap-x-6 gap-y-4">
        <Segmented label="State" options={STATES} value={filters.state} onChange={(state) => setFilters({ state })} />
        <Select
          label="Severity"
          wrapperClassName="w-full sm:w-auto sm:min-w-[10rem]"
          value={filters.severity}
          onChange={(e) => setFilters({ severity: e.target.value as AlertFilters['severity'] })}
        >
          <option value="all">All severities</option>
          <option value="critical">Critical</option>
          <option value="warning">Warning</option>
          <option value="info">Info</option>
        </Select>
        <Select
          label="About"
          wrapperClassName="w-full sm:w-auto sm:min-w-[12rem]"
          value={filters.category}
          onChange={(e) => setFilters({ category: e.target.value as AlertFilters['category'] })}
        >
          <option value="all">The machine and its monitoring</option>
          <option value="machine">The machine</option>
          <option value="monitoring">The monitoring</option>
        </Select>
        <Select
          label="Raised by"
          wrapperClassName="w-full sm:w-auto sm:min-w-[12rem]"
          value={filters.kind}
          onChange={(e) => setFilters({ kind: e.target.value as AlertFilters['kind'] })}
        >
          <option value="all">Anything</option>
          {ALERT_KINDS.map((k) => <option key={k} value={k}>{KIND_WORDS[k]}</option>)}
        </Select>
        <Select label="Machine" wrapperClassName="w-full sm:w-auto sm:min-w-[12rem]" value={filters.machine} onChange={(e) => setFilters({ machine: e.target.value })}>
          <option value="">All machines</option>
          {machineOptions.map((m) => (
            <option key={m.id} value={m.id}>{m.name}</option>
          ))}
        </Select>
      </div>
      </FilterDisclosure>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-meta text-surface-600 dark:text-surface-400">
        <p>
          {updatedAt ? (
            <>Last updated <Time value={updatedAt} format="datetime" />. Refreshes every {REFRESH_MS / 1000} seconds while this tab is visible.</>
          ) : (
            'Waiting for the first answer.'
          )}
        </p>
        <Button size="small" variant="ghost" onClick={alerts.retry} pending={alerts.loading && hasData}>Refresh now</Button>
      </div>

      {/* a filter change and a refresh both change this sentence, so it is announced politely. It is always in the page, so the
          empty and error results are announced too. */}
      <p role="status" className="sr-only">
        {!hasData ? '' : available === 0 ? 'No alerts match these filters.' : `${summary}.`}
      </p>
      {/* announces the outcome of a resolve, never a refresh */}
      <div role="status" className="text-base text-surface-800 dark:text-surface-200">{notice}</div>
      {actionError && <ErrorNotice message="Some alerts were not resolved." detail={actionError.text} requestId={actionError.ref} />}
      {machines.error && !machines.data && (
        <p className="text-meta text-surface-600 dark:text-surface-400">Machine names could not be loaded, so names are read from the alert text.</p>
      )}

      {alerts.error && hasData && (
        <ErrorNotice message={alerts.error} detail={updatedAt ? `Showing the list from ${formatDateTime(updatedAt)}.` : undefined} requestId={alerts.errorRef} onRetry={alerts.retry} pending={alerts.loading} />
      )}

      {!hasData && alerts.error ? (
        <ErrorNotice message={alerts.error} detail="No alerts are shown because the list could not be loaded. This is not the same as no alerts." requestId={alerts.errorRef} onRetry={alerts.retry} pending={alerts.loading} />
      ) : !hasData ? (
        <SkeletonRows rows={6} label="Loading alerts" />
      ) : available === 0 && !hasNarrowingFilters(filters) ? (
        <Panel bodyClassName="p-0">
          <EmptyState
            heading={filters.state === 'active' ? 'No active alerts' : 'No resolved alerts yet'}
            subMessage={filters.state === 'active' ? 'Nothing has broken a rule or been flagged by the model. No sensor or node has raised a monitoring alert.' : 'Alerts appear here once they are resolved. A person resolves most of them and a monitoring alert resolves itself.'}
          />
        </Panel>
      ) : available === 0 ? (
        <Panel bodyClassName="p-0">
          <EmptyState
            heading="No alerts match these filters"
            subMessage={`${hasNarrowingFilters(filters) ? 'Clear the filters to see everything that is ' + (filters.state === 'active' ? 'active' : 'resolved') + '.' : ''}`}
            action={hasNarrowingFilters(filters) ? { label: 'Clear filters', onClick: () => setFilters({ severity: DEFAULT_ALERT_FILTERS.severity, kind: DEFAULT_ALERT_FILTERS.kind, machine: DEFAULT_ALERT_FILTERS.machine, category: DEFAULT_ALERT_FILTERS.category }) } : undefined}
          />
        </Panel>
      ) : (
        <>
          <AlertList
            title={stateWord}
            description={modelCount > 0 ? `${summary}, ${modelCount} from the anomaly model` : summary}
            alerts={matching}
            deviceNames={{ ...fallbackNames, ...deviceNames }}
            canAct={filters.state === 'active' && canWrite}
            pendingIds={pendingIds}
            onResolve={(a) => (a.still_occurring === true ? setConfirm(a) : resolveIds([a.id]))}
          />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-base text-surface-700 dark:text-surface-300">
              Showing <span className="tabular-nums">{available}</span> {available === 1 ? 'alert' : 'alerts'}
              {alerts.total !== null && alerts.hasMore ? <> of <span className="tabular-nums">{alerts.total}</span></> : null}.
              {alerts.hasMore ? '' : ' That is all of them.'}
            </p>
            {alerts.hasMore && (
              <Button variant="secondary" onClick={alerts.loadMore} pending={alerts.loadingMore}>
                Load older alerts
              </Button>
            )}
          </div>
        </>
      )}

      <ConfirmDialog
        open={confirm !== null}
        destructive={false}
        title="Resolve an alert that is still occurring?"
        confirmLabel="Resolve"
        pending={confirm ? pendingIds.has(confirm.id) : false}
        onCancel={() => setConfirm(null)}
        onConfirm={async () => {
          if (!confirm) return;
          await resolveIds([confirm.id]);
          setConfirm(null);
        }}
      >
        {confirm && (
          <p>
            The condition behind this alert for {nameOf(confirm.device_id)} is still occurring. Resolving it by hand does not fix the machine and the alert is not raised again for an hour. A resolved alert cannot be reopened.
          </p>
        )}
      </ConfirmDialog>
    </div>
  );
}
