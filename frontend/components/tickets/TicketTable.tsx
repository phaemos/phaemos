'use client';

import type { Ticket } from '@/types';
import { ticketTitle } from './ticketTitle';
import DataTable from '@/components/ui/DataTable';
import StatusBadge from '@/components/ui/StatusBadge';
import Time from '@/components/ui/Time';
import { formatDate, formatDateTime, formatDateTimeExact } from '@/lib/format';
import { assigneeLabel, formatTicketNumber, type AssigneeContext } from '@/lib/ticketView';

interface Props {
  tickets: Ticket[];
  // machine id to name, so a ticket shows the machine and not its id
  deviceNames: Record<string, string>;
  assignees: AssigneeContext;
  // the ticket open in the detail panel
  selectedId: string;
  onOpen: (id: string) => void;
}

function When({ iso, full }: { iso: string; full?: boolean }) {
  return (
    <Time value={iso} format={full ? 'datetime' : 'date'} className="whitespace-nowrap" />
  );
}

// the list of tickets. Each title opens the ticket in the detail panel above the table.
export default function TicketTable({ tickets, deviceNames, assignees, selectedId, onOpen }: Props) {
  return (
    <DataTable caption="Maintenance tickets, newest first">
      <thead>
        <tr>
          <th scope="col">Ticket</th>
          <th scope="col">Title</th>
          <th scope="col">Machine</th>
          <th scope="col">Status</th>
          <th scope="col">Priority</th>
          <th scope="col">Assignee</th>
          <th scope="col">Opened</th>
          <th scope="col">Updated</th>
        </tr>
      </thead>
      <tbody>
        {tickets.map((t) => (
          <tr key={t.id}>
            <td className="whitespace-nowrap font-mono tabular-nums text-surface-700 dark:text-surface-300">{formatTicketNumber(t.ticket_number)}</td>
            <td className="max-w-xs">
              <button
                type="button"
                id={`open-ticket-${t.id}`}
                aria-current={t.id === selectedId ? 'true' : undefined}
                onClick={() => onOpen(t.id)}
                className="inline-flex min-h-[44px] max-w-full items-center text-left font-medium text-brand-800 underline-offset-2 hover:underline aria-[current=true]:underline dark:text-brand-400"
              >
                <span className="truncate">{ticketTitle(t.title)}</span>
                <span className="sr-only">, open {formatTicketNumber(t.ticket_number)}</span>
              </button>
            </td>
            <td className="text-surface-800 dark:text-surface-200">{t.device_id ? (deviceNames[t.device_id] ?? 'Unknown machine') : 'No machine'}</td>
            <td><StatusBadge status={t.status} /></td>
            <td>{t.priority ? <StatusBadge status={t.priority} /> : <span className="text-surface-600 dark:text-surface-400">Not set</span>}</td>
            <td className="text-surface-800 dark:text-surface-200">{assigneeLabel(t.assigned_to, assignees)}</td>
            <td className="text-surface-700 dark:text-surface-300"><When iso={t.created_at} /></td>
            <td className="text-surface-700 dark:text-surface-300"><When iso={t.updated_at} full /></td>
          </tr>
        ))}
      </tbody>
    </DataTable>
  );
}
