'use client';

import { useCallback, useMemo, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useApiResource } from '@/hooks/useApiResource';
import type { Device, Ticket, User } from '@/types';
import Button from '@/components/ui/Button';
import EmptyState from '@/components/ui/EmptyState';
import ErrorNotice from '@/components/ui/ErrorNotice';
import PageHeader from '@/components/ui/PageHeader';
import Panel from '@/components/ui/Panel';
import { Select } from '@/components/ui/Input';
import { SkeletonRows } from '@/components/ui/Skeleton';
import { PRIORITY_ORDER, TICKET_PRIORITY, TICKET_STATUS } from '@/lib/status';
import { filterTickets, newestFirst, parseTicketFilters, ticketFiltersToQuery, type AssigneeContext, type TicketFilters } from '@/lib/ticketView';
import { useRole } from '@/hooks/useRole';
import { canWrite as canWriteRole } from '@/lib/role';
import ReadOnlyNote from '@/components/ui/ReadOnlyNote';
import TicketDetail from './TicketDetail';
import TicketDialog from './TicketDialog';
import TicketForm from './TicketForm';
import TicketTable from './TicketTable';

// one request asks for this many tickets and machines. The API default is 20 and returns no total.
const LIMIT = 200;
const STEP = 25;

export default function TicketsView() {
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const filters = useMemo(() => parseTicketFilters(search), [search]);
  const listKey = `${filters.status}|${filters.priority}`;

  const setFilters = useCallback(
    (patch: Partial<TicketFilters>) => {
      const next = ticketFiltersToQuery({ ...filters, ...patch });
      router.replace(next ? `${pathname}?${next}` : pathname, { scroll: false });
    },
    [filters, pathname, router],
  );

  // status and priority are asked of the server, so a filter over a fleet with more tickets than a page is still right
  const tickets = useApiResource<Ticket[]>('/tickets', { params: { limit: LIMIT, status: filters.status === 'all' ? undefined : filters.status, priority: filters.priority === 'all' ? undefined : filters.priority }, what: 'The tickets' });
  const machines = useApiResource<Device[]>('/devices', { params: { limit: LIMIT }, what: 'The machine names' });
  const me = useApiResource<User>('/auth/me', { what: 'Your account' });
  // only an admin may list users (GET /users), so other roles get no names beyond their own
  const canListUsers = me.data?.role === 'admin';
  const role = useRole();
  // until the role is known no write control is offered, so a viewer never sees "New ticket" flash
  const canWrite = canWriteRole(role);
  const users = useApiResource<User[]>('/users', { params: { limit: LIMIT }, enabled: canListUsers, what: 'The user list' });

  // a saved ticket replaces its row at once, so the table does not wait for the next fetch
  const [edits, setEdits] = useState<Record<string, Ticket>>({});
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [reveal, setReveal] = useState({ key: '', count: STEP });
  const count = reveal.key === listKey ? reveal.count : STEP;

  const all = useMemo(() => newestFirst((tickets.data ?? []).map((t) => edits[t.id] ?? t)), [tickets.data, edits]);
  const matching = useMemo(() => filterTickets(all, filters), [all, filters]);
  const deviceNames = useMemo(() => Object.fromEntries((machines.data ?? []).map((d) => [d.id, d.name])), [machines.data]);
  const assignees: AssigneeContext = useMemo(
    () => ({ meId: me.data?.id ?? null, people: canListUsers && users.data ? users.data : null }),
    [me.data, canListUsers, users.data],
  );

  // a linked ticket older than the loaded window is fetched on its own
  const inList = all.find((t) => t.id === filters.ticket);
  const lone = useApiResource<Ticket>(filters.ticket ? `/tickets/${filters.ticket}` : null, { enabled: Boolean(filters.ticket) && !inList && Boolean(tickets.data), what: 'That ticket' });
  const selected = inList ?? (filters.ticket && lone.data ? (edits[filters.ticket] ?? lone.data) : null);

  function closeDetail(id: string) {
    setFilters({ ticket: '' });
    // the title button that opened it takes focus back once the panel is gone
    requestAnimationFrame(() => document.getElementById(`open-ticket-${id}`)?.focus());
  }

  const shown = matching.slice(0, count);
  const narrowed = filters.status !== 'all' || filters.priority !== 'all';

  return (
    <div className="space-y-6">
      <PageHeader
        title="Maintenance tickets"
        description="Work raised by people and by the anomaly model, newest first."
        actions={canWrite ? <Button onClick={() => setCreating(true)}>New ticket</Button> : undefined}
      />

      {role === 'viewer' && <ReadOnlyNote>You can read every ticket here. Creating a ticket and changing one are for technicians and admins.</ReadOnlyNote>}

      <div role="group" aria-label="Filter tickets" className="flex flex-wrap items-end gap-x-6 gap-y-4">
        <Select label="Status" wrapperClassName="w-full sm:w-auto sm:min-w-[11rem]" value={filters.status} onChange={(e) => setFilters({ status: e.target.value as TicketFilters['status'] })}>
          <option value="all">All statuses</option>
          {(Object.keys(TICKET_STATUS) as (keyof typeof TICKET_STATUS)[]).map((k) => (
            <option key={k} value={k}>{TICKET_STATUS[k].word}</option>
          ))}
        </Select>
        <Select label="Priority" wrapperClassName="w-full sm:w-auto sm:min-w-[11rem]" value={filters.priority} onChange={(e) => setFilters({ priority: e.target.value as TicketFilters['priority'] })}>
          <option value="all">All priorities</option>
          {PRIORITY_ORDER.map((k) => (
            <option key={k} value={k}>{TICKET_PRIORITY[k].word}</option>
          ))}
        </Select>
        {narrowed && <Button variant="ghost" onClick={() => setFilters({ status: 'all', priority: 'all' })}>Clear filters</Button>}
      </div>

      <p role="status" className="sr-only">{tickets.data ? `${matching.length} ${matching.length === 1 ? 'ticket matches' : 'tickets match'} the filters.` : ''}</p>
      <div role="status" className="text-base text-surface-800 dark:text-surface-200">{notice}</div>

      {selected && (
        <TicketDetail
          key={selected.id}
          ticket={selected}
          machineName={selected.device_id ? (deviceNames[selected.device_id] ?? null) : null}
          assignees={assignees}
          canListUsers={canListUsers}
          readOnly={!canWrite}
          onSaved={(t) => setEdits((prev) => ({ ...prev, [t.id]: t }))}
          onClose={() => closeDetail(selected.id)}
        />
      )}
      {filters.ticket && !selected && tickets.data && lone.error && (
        <ErrorNotice message="That ticket could not be opened." detail={lone.error} onRetry={lone.retry} />
      )}

      {tickets.error && tickets.data && <ErrorNotice message={tickets.error} detail="Showing the tickets from the last time they loaded." onRetry={tickets.retry} pending={tickets.loading} />}

      {!tickets.data && tickets.error ? (
        <ErrorNotice message={tickets.error} detail="No tickets are shown because the list could not be loaded. This is not the same as no tickets." onRetry={tickets.retry} pending={tickets.loading} />
      ) : !tickets.data ? (
        <SkeletonRows rows={6} label="Loading tickets" />
      ) : all.length === 0 ? (
        <Panel bodyClassName="p-0">
          <EmptyState
            heading="No tickets yet"
            subMessage={canWrite ? 'Raise one with New ticket. The anomaly model also opens a ticket when it raises an alert.' : 'The anomaly model opens a ticket when it raises an alert. Technicians and admins can raise one by hand.'}
            action={canWrite ? { label: 'New ticket', onClick: () => setCreating(true) } : undefined}
          />
        </Panel>
      ) : matching.length === 0 ? (
        <Panel bodyClassName="p-0">
          <EmptyState
            heading="No tickets match these filters"
            subMessage={`${all.length} ${all.length === 1 ? 'ticket' : 'tickets'} in all.`}
            action={{ label: 'Clear filters', onClick: () => setFilters({ status: 'all', priority: 'all' }) }}
          />
        </Panel>
      ) : (
        <>
          <Panel bodyClassName="p-0">
            <TicketTable tickets={shown} deviceNames={deviceNames} assignees={assignees} selectedId={selected?.id ?? ''} onOpen={(id) => setFilters({ ticket: id })} />
          </Panel>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-base text-surface-700 dark:text-surface-300">
              Showing <span className="tabular-nums">{shown.length}</span> of <span className="tabular-nums">{matching.length}</span> {narrowed ? 'matching ' : ''}{matching.length === 1 ? 'ticket' : 'tickets'}
              {tickets.total !== null && tickets.total > all.length ? `. This page holds the newest ${all.length} of ${tickets.total} tickets.` : '.'}
            </p>
            {shown.length < matching.length && (
              <Button variant="secondary" onClick={() => setReveal({ key: listKey, count: count + STEP })}>
                Show {Math.min(STEP, matching.length - shown.length)} more
              </Button>
            )}
          </div>
        </>
      )}

      <TicketDialog open={creating} title="New ticket" onClose={() => setCreating(false)}>
        <TicketForm
          onCancel={() => setCreating(false)}
          onSuccess={() => {
            setCreating(false);
            setEdits({});
            setNotice('Ticket created.');
            tickets.retry();
          }}
        />
      </TicketDialog>
    </div>
  );
}
