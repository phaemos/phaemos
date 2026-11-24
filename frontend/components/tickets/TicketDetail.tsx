'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import api from '@/lib/api';
import { describeApiError } from '@/lib/apiError';
import type { Ticket } from '@/types';
import { ticketTitle } from './ticketTitle';
import Button from '@/components/ui/Button';
import ErrorNotice from '@/components/ui/ErrorNotice';
import { Select } from '@/components/ui/Input';
import StatusBadge from '@/components/ui/StatusBadge';
import ReadOnlyNote from '@/components/ui/ReadOnlyNote';
import { PRIORITY_ORDER, TICKET_PRIORITY, TICKET_STATUS } from '@/lib/status';
import { formatDateTime, formatDateTimeExact } from '@/lib/format';
import {
  assigneeOptions,
  buildTicketPatch,
  draftFromTicket,
  formatTicketNumber,
  type AssigneeContext,
  type TicketDraft,
  type TicketPriorityKey,
  type TicketStatusKey,
} from '@/lib/ticketView';
import Time from '@/components/ui/Time';

const STATUS_KEYS = Object.keys(TICKET_STATUS) as TicketStatusKey[];

interface EditorProps {
  ticket: Ticket;
  assignees: AssigneeContext;
  canListUsers: boolean;
  onSaved: (ticket: Ticket) => void;
}

// the draft lives here and this component is keyed by the ticket's updated_at, so a save resets it to the new values
function Editor({ ticket, assignees, canListUsers, onSaved }: EditorProps) {
  const [draft, setDraft] = useState<TicketDraft>(() => draftFromTicket(ticket));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const patch = buildTicketPatch(ticket, draft);
  const changed = Object.keys(patch).length > 0;
  const options = assigneeOptions(ticket.assigned_to, assignees);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!changed) return;
    setPending(true);
    setError(null);
    try {
      const res = await api.patch<Ticket>(`/tickets/${ticket.id}`, patch);
      onSaved(res.data);
    } catch (err) {
      setError(describeApiError(err, 'The ticket'));
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={save} className="space-y-4">
      {error && <ErrorNotice message="The changes were not saved." detail={error} />}
      <div className="grid gap-4 sm:grid-cols-3">
        <Select label="Status" value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value as TicketStatusKey })}>
          {STATUS_KEYS.map((k) => (
            <option key={k} value={k}>{TICKET_STATUS[k].word}</option>
          ))}
        </Select>
        <Select
          label="Priority"
          value={draft.priority}
          onChange={(e) => setDraft({ ...draft, priority: e.target.value as TicketPriorityKey })}
          hint={ticket.priority ? undefined : 'Not set yet.'}
        >
          {!ticket.priority && <option value="">Not set</option>}
          {[...PRIORITY_ORDER].reverse().map((k) => (
            <option key={k} value={k}>{TICKET_PRIORITY[k].word}</option>
          ))}
        </Select>
        <Select
          label="Assignee"
          value={draft.assigned_to}
          onChange={(e) => setDraft({ ...draft, assigned_to: e.target.value })}
          hint={canListUsers ? undefined : 'Only admins can see other users, so you can keep the assignee or take the ticket.'}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </Select>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" pending={pending} disabled={!changed}>Save changes</Button>
        {!changed && <p className="text-meta text-surface-600 dark:text-surface-400">Change a field to save.</p>}
      </div>
    </form>
  );
}

interface Props {
  ticket: Ticket;
  machineName: string | null;
  assignees: AssigneeContext;
  canListUsers: boolean;
  // a viewer reads the ticket and cannot change it: the API answers 403, so the form is not offered
  readOnly?: boolean;
  onSaved: (ticket: Ticket) => void;
  onClose: () => void;
}

// one ticket in full, with the three fields the API lets a person change
export default function TicketDetail({ ticket, machineName, assignees, canListUsers, readOnly = false, onSaved, onClose }: Props) {
  const heading = useRef<HTMLHeadingElement>(null);
  const [saved, setSaved] = useState<string | null>(null);

  // focus moves to the heading when a ticket opens, so a keyboard or screen reader user lands on it
  useEffect(() => {
    heading.current?.focus();
  }, [ticket.id]);

  return (
    <section aria-labelledby="ticket-detail-title" className="rounded-lg border border-surface-200 bg-surface-0 dark:border-surface-800 dark:bg-surface-900">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-surface-200 px-4 py-3 dark:border-surface-800">
        <div className="min-w-0">
          <p className="num mb-1 text-meta text-surface-600 dark:text-surface-400">{formatTicketNumber(ticket.ticket_number)}</p>
          <h2 id="ticket-detail-title" ref={heading} tabIndex={-1} className="text-base font-semibold text-surface-900 dark:text-surface-50">
            {ticketTitle(ticket.title)}
          </h2>
        </div>
        <Button variant="secondary" onClick={onClose}>Close ticket<span className="sr-only"> {formatTicketNumber(ticket.ticket_number)}</span></Button>
      </header>
      <div className="space-y-5 p-4">
        <dl className="grid gap-x-8 gap-y-3 text-base sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <dt className="label text-surface-700 dark:text-surface-300">Machine</dt>
            <dd className="mt-1 text-surface-900 dark:text-surface-50">
              {ticket.device_id ? (
                <Link href={`/devices/${ticket.device_id}`} className="font-medium text-brand-800 underline underline-offset-2 dark:text-brand-400">{machineName ?? 'Unknown machine'}</Link>
              ) : (
                'No machine'
              )}
            </dd>
          </div>
          <div>
            <dt className="label text-surface-700 dark:text-surface-300">Current</dt>
            <dd className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
              <StatusBadge status={ticket.status} />
              {ticket.priority && <StatusBadge status={ticket.priority} />}
            </dd>
          </div>
          <div>
            <dt className="label text-surface-700 dark:text-surface-300">Opened</dt>
            <dd className="mt-1 tabular-nums text-surface-900 dark:text-surface-50"><Time value={ticket.created_at} /></dd>
          </div>
          <div>
            <dt className="label text-surface-700 dark:text-surface-300">Updated</dt>
            <dd className="mt-1 tabular-nums text-surface-900 dark:text-surface-50"><Time value={ticket.updated_at} /></dd>
          </div>
        </dl>
        {ticket.description ? (
          <p className="max-w-[72ch] whitespace-pre-wrap text-base text-surface-800 dark:text-surface-200">{ticket.description}</p>
        ) : (
          <p className="text-base text-surface-600 dark:text-surface-400">No description.</p>
        )}
        {readOnly ? (
          <ReadOnlyNote>The status, priority and assignee are shown above. Changing them is for technicians and admins.</ReadOnlyNote>
        ) : (
        <Editor
          key={ticket.updated_at}
          ticket={ticket}
          assignees={assignees}
          canListUsers={canListUsers}
          onSaved={(t) => {
            setSaved(`Saved at ${formatDateTime(t.updated_at)}.`);
            onSaved(t);
          }}
        />
        )}
        <p role="status" className="text-base text-surface-800 dark:text-surface-200">{saved}</p>
      </div>
    </section>
  );
}
