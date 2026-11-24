'use client';

import { useCallback, useEffect, useMemo, useReducer, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import type { Alert, Device, MlStatus } from '@/types';
import api from '@/lib/api';
import { describeApiError } from '@/lib/apiError';
import { requestIdOf } from '@/lib/apiCode';
import { useApiResource } from '@/hooks/useApiResource';
import { useRole } from '@/hooks/useRole';
import { useOwnerContext } from '@/hooks/useOwnerContext';
import { useToast } from '@/hooks/useToast';
import Button from '@/components/ui/Button';
import EmptyState from '@/components/ui/EmptyState';
import ErrorNotice from '@/components/ui/ErrorNotice';
import { Input, Select } from '@/components/ui/Input';
import PageHeader from '@/components/ui/PageHeader';
import Panel from '@/components/ui/Panel';
import { SkeletonRows } from '@/components/ui/Skeleton';
import MachineTable from '@/components/machines/MachineTable';
import AddMachineDialog from '@/components/machines/AddMachineDialog';
import FirmwareDialog from '@/components/machines/FirmwareDialog';
import KeyOnceDialog from '@/components/machines/KeyOnceDialog';
import { CLOSED, keyReducer } from '@/lib/keyOnce';
import { countLine, machineViewToQuery, parseMachineView, SORT_OPTIONS, sortMachines, tagCounts, type MachineView, type SortKey } from '@/lib/machineList';
import { LINK_STATE, MACHINE_HEALTH } from '@/lib/status';
import { alertsGap, linkOf, machineStatus } from '@/lib/machineState';
import { AlertsGapProvider } from './AlertsGap';
import { serverNow } from '@/lib/serverClock';

// the most machines one request asks for. The API default is 20 and it has no total, so the page asks for a whole
// fleet at once and says so when the answer reaches this number.
const LIMIT = 200;
const ALERT_LIMIT = 500;

export default function MachinesView() {
  const role = useRole();
  const isAdmin = role === 'admin';
  const { addToast } = useToast();
  // the search and the tag are asked of the server, because filtering one page of machines here would be wrong once the fleet is larger
  // than a page. The search waits for a pause in typing so each key does not make a request.
  const [typed, setTyped] = useState<string | null>(null);
  const urlSearch = useSearchParams().get('search') ?? '';
  const [debounced, setDebounced] = useState(urlSearch.trim());
  const wanted = (typed ?? urlSearch).trim();
  useEffect(() => {
    const t = setTimeout(() => setDebounced(wanted), 300);
    return () => clearTimeout(t);
  }, [wanted]);
  const tagParam = useSearchParams().get('tag') ?? '';
  const { data, error, errorRef, loading, retry, total, stale } = useApiResource<Device[]>('/devices', { params: { limit: LIMIT, search: debounced || undefined, tag: tagParam || undefined }, what: 'The machines', intervalMs: 15000, keepPrevious: true });
  // the rest of a fleet larger than one read: the next machines are read by offset and added after the first read. They are dropped when the
  // search or the tag changes, because they belonged to the old question.
  const askKey = `${debounced}|${tagParam}`;
  const [extra, setExtra] = useState<{ key: string; rows: Device[] }>({ key: askKey, rows: [] });
  const [loadingRest, setLoadingRest] = useState(false);
  const [restError, setRestError] = useState<{ text: string; ref: string | null } | null>(null);
  // every tag in use, from the whole fleet, so choosing one does not shrink the list of tags
  const everyone = useApiResource<Device[]>('/devices', { params: { limit: LIMIT }, what: 'The machine tags', intervalMs: 60_000 });
  const owners = useOwnerContext(isAdmin, role !== null);
  // the refusal behind a machine with no model. The list works without it, so a failed read only loses that sentence.
  const ml = useApiResource<MlStatus>('/ml/status', { what: 'The model status', intervalMs: 60_000 });
  // the active machine alerts say which machines are in warning or fault. Monitoring alerts are about the link, not the machine.
  // the API sends at most 500 and says in X-Total-Count how many there are, so a cut-off read is known and not mistaken for all
  const alertsResource = useApiResource<Alert[]>('/alerts', { params: { resolved: false, category: 'machine', limit: ALERT_LIMIT }, what: 'The alerts', intervalMs: 15000 });
  const alerts = useMemo(() => alertsResource.data ?? [], [alertsResource.data]);
  const gap = alertsGap(alertsResource);

  // the search, the filters and the sort order live in the address so a view can be linked and survives a reload
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const view = useMemo(() => parseMachineView(params), [params]);
  const { search, state, link, tag, sort } = view;
  const setView = useCallback(
    (patch: Partial<MachineView>) => {
      const next = machineViewToQuery({ ...view, ...patch });
      router.replace(next ? `${pathname}?${next}` : pathname, { scroll: false });
    },
    [view, pathname, router],
  );

  // a dialog gets a new key each time it opens, so it starts with empty fields
  const [addOpen, setAddOpen] = useState(false);
  const [addKey, setAddKey] = useState(0);
  // the key of a machine just added, shown once and dropped when its dialog is closed
  const [newKey, dispatchKey] = useReducer(keyReducer, CLOSED);
  const [keyFor, setKeyFor] = useState('');
  const [keyMissing, setKeyMissing] = useState<string | null>(null);
  const [fwOpen, setFwOpen] = useState(false);
  const [fwKey, setFwKey] = useState(0);

  const restRows = useMemo(() => (extra.key === askKey ? extra.rows : []), [extra, askKey]);
  const all = useMemo(() => {
    const first = data ?? [];
    const have = new Set(first.map((d) => d.id));
    return [...first, ...restRows.filter((d) => !have.has(d.id))];
  }, [data, restRows]);
  const hasRest = total !== null && total > all.length;
  async function loadRest() {
    setLoadingRest(true);
    setRestError(null);
    try {
      const res = await api.get<Device[]>('/devices', { params: { limit: LIMIT, offset: all.length, search: debounced || undefined, tag: tagParam || undefined } });
      setExtra({ key: askKey, rows: [...restRows, ...res.data] });
    } catch (err) {
      setRestError({ text: describeApiError(err, 'The machines'), ref: requestIdOf(err) ?? null });
    } finally {
      setLoadingRest(false);
    }
  }
  const tags = useMemo(() => tagCounts(everyone.data ?? all), [everyone.data, all]);
  // each machine's state worked out once, from its link and its active alerts
  const states = useMemo(() => new Map(all.map((m) => [m.id, { link: linkOf(m, serverNow()), machine: machineStatus(m, alerts, serverNow(), gap).state }])), [all, alerts, gap]);
  const shown = useMemo(() => {
    const narrowed = all.filter(
      (m) => (!link || states.get(m.id)?.link === link) && (!state || states.get(m.id)?.machine === state),
    );
    // worst first: a fault, then a warning, then a machine nobody can see, then a late node, then the healthy ones
    const rank = (m: Device) => {
      const st = states.get(m.id);
      if (st?.machine === 'fault') return 0;
      if (st?.machine === 'warning') return 1;
      if (st?.machine === 'unknown') return 2;
      return st?.link === 'late' ? 3 : 4;
    };
    return sortMachines(narrowed, sort, rank);
  }, [all, states, link, state, sort]);
  const filtering = state !== '' || link !== '' || tag !== '' || search.trim() !== '';

  const clearFilters = () => setView({ search: '', state: '', link: '', tag: '' });

  const actions = isAdmin ? (
    <>
      <Button variant="secondary" onClick={() => { setFwKey((k) => k + 1); setFwOpen(true); }}>Update firmware by tag</Button>
      <Button onClick={() => { setAddKey((k) => k + 1); setAddOpen(true); }}>Add a machine</Button>
    </>
  ) : undefined;

  let body;
  if (loading) {
    body = <div className="p-4"><SkeletonRows rows={6} label="Loading machines" /></div>;
  } else if (!data) {
    body = <div className="p-4"><ErrorNotice message={error ?? 'The machines did not load.'} requestId={errorRef} onRetry={retry} /></div>;
  } else if (all.length === 0) {
    body = (
      <EmptyState
        heading="No machines yet"
        subMessage={isAdmin ? 'Add a machine to get its API key. It appears here as soon as its node posts a reading.' : 'An admin adds machines. They appear here once they exist.'}
        action={isAdmin ? { label: 'Add a machine', onClick: () => { setAddKey((k) => k + 1); setAddOpen(true); } } : undefined}
      />
    );
  } else if (shown.length === 0) {
    body = <EmptyState heading="No machine matches" subMessage="Change the search or the filters to see more." action={{ label: 'Clear filters', onClick: clearFilters }} />;
  } else {
    body = <MachineTable machines={shown} alerts={alerts} owners={owners} ownersReady={owners.ready} ml={ml.data} />;
  }

  return (
    <AlertsGapProvider gap={gap}>
    <div className="space-y-6">
      <PageHeader title="Machines" description="Every machine, its node and when it last reported." actions={actions} />

      {keyMissing && <ErrorNotice message={`${keyMissing} was added but the API did not return its key.`} detail="Open the machine and replace its API key to get one." />}
      {data && error && <ErrorNotice message="The machines could not be refreshed. This list may be out of date." onRetry={retry} />}
      {data && gap && (alertsResource.error || alertsResource.data) && <ErrorNotice message="Machines with no active alert show as Unknown." detail={`That is because ${gap}. A machine is not called healthy while its alerts are unknown.`} onRetry={alertsResource.retry} />}

    {data && all.length > 0 && (
      <form role="search" aria-label="Filter machines" onSubmit={(e) => e.preventDefault()} className="flex flex-wrap items-end gap-3">
        <Input label="Search by name" type="search" value={typed ?? search} onChange={(e) => { setTyped(e.target.value); setView({ search: e.target.value }); }} wrapperClassName="w-full sm:w-56" autoComplete="off" />
        <Select label="Machine state" value={state} onChange={(e) => setView({ state: e.target.value })} wrapperClassName="w-full sm:w-40">
          <option value="">Any state</option>
          {Object.entries(MACHINE_HEALTH).map(([key, h]) => <option key={key} value={key}>{h.word}</option>)}
        </Select>
        <Select label="Monitoring link" value={link} onChange={(e) => setView({ link: e.target.value })} wrapperClassName="w-full sm:w-44">
          <option value="">Any link</option>
          {Object.entries(LINK_STATE).map(([key, l]) => <option key={key} value={key}>{l.word}</option>)}
        </Select>
        <Select label="Tag" value={tag} onChange={(e) => setView({ tag: e.target.value })} wrapperClassName="w-full sm:w-44">
          <option value="">All tags</option>
          {tags.map((t) => <option key={t.tag} value={t.tag}>{t.tag} ({t.count})</option>)}
        </Select>
        <Select label="Sort by" value={sort} onChange={(e) => setView({ sort: e.target.value as SortKey })} wrapperClassName="w-full sm:w-56">
          {SORT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </Select>
        {filtering && <Button variant="ghost" onClick={clearFilters}>Clear filters</Button>}
      </form>
    )}
    {/* the rows stay while the server answers a search. The line is always there, so nothing moves and its words are heard once. */}
    <p role="status" className="-mt-3 min-h-5 text-meta text-surface-700 dark:text-surface-300">{stale || wanted !== debounced ? 'Searching' : ''}</p>

      <Panel
        bodyClassName=""
        title={data && all.length > 0 ? countLine(shown.length, all.length) : 'Machines'}
        description={data && hasRest ? `Read ${all.length} of ${total} machines so far.` : undefined}
      >
        {body}
        {data && hasRest && (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-surface-200 px-4 py-3 dark:border-surface-800">
            <p className="text-base text-surface-800 dark:text-surface-200">
              This list holds <span className="tabular-nums">{all.length}</span> of <span className="tabular-nums">{total}</span> machines. The rest have not been read.
            </p>
            <Button variant="secondary" onClick={loadRest} pending={loadingRest}>Read the next machines</Button>
          </div>
        )}
        {restError && <div className="p-4"><ErrorNotice message={restError.text} requestId={restError.ref} onRetry={loadRest} pending={loadingRest} /></div>}
      </Panel>

      {isAdmin && (
        <>
          <AddMachineDialog
            key={`add-${addKey}`}
            open={addOpen}
            onClose={() => setAddOpen(false)}
            users={owners.users}
            onCreated={(machine, key) => {
              setAddOpen(false);
              setKeyFor(machine.name);
              if (key) { setKeyMissing(null); dispatchKey({ type: 'show', key }); } else setKeyMissing(machine.name);
              retry();
            }}
          />
          <KeyOnceDialog state={newKey} dispatch={dispatchKey} machineName={keyFor} rotated={false} />
          <FirmwareDialog
            key={`fw-${fwKey}`}
            open={fwOpen}
            onClose={() => setFwOpen(false)}
            tags={tags}
            onQueued={(message) => addToast('success', message)}
          />
        </>
      )}
    </div>
    </AlertsGapProvider>
  );
}
