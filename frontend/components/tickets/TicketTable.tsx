'use client';

// I implement sorting as local state because ticket lists are short enough
// that client-side sort is instant and avoids a round-trip to the server on
// every column header click.

import { useState } from 'react';
import type { Ticket } from '../../types/index';
import LoadingSkeleton from '../ui/LoadingSkeleton';
import { formatDate } from '../../lib/utils';

interface Props {
  tickets: Ticket[];
  loading: boolean;
}

type SortKey = 'ticket_number' | 'title' | 'status' | 'priority' | 'device_id' | 'assigned_to' | 'created_at';
type SortDir = 'asc' | 'desc';

function formatTicketNumber(n: number | null): string {
  if (n == null) return '-';
  return `PHM-${n.toString().padStart(4, '0')}`;
}

// I define priority weight so sorting by priority produces a meaningful
// ordering (critical first) rather than alphabetical.
const PRIORITY_WEIGHT: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

const STATUS_WEIGHT: Record<string, number> = {
  open: 0,
  in_progress: 1,
  closed: 2,
};

function pillClasses(value: string): string {
  switch (value) {
    case 'open':
      return 'bg-primary-100 dark:bg-primary-600/20 text-primary-600 dark:text-primary-400 border border-primary-100 dark:border-primary-600/30';
    case 'in_progress':
      return 'bg-warning-50 dark:bg-warning-600/20 text-warning-600 dark:text-warning-500 border border-warning-50 dark:border-warning-600/30';
    case 'closed':
      return 'bg-surface-100 dark:bg-surface-800 text-surface-600 dark:text-surface-400 border border-surface-200 dark:border-surface-700';
    case 'critical':
      return 'bg-critical-50 dark:bg-critical-600/20 text-critical-600 dark:text-critical-400 border border-critical-50 dark:border-critical-600/30';
    case 'high':
      return 'bg-warning-50 dark:bg-warning-600/20 text-warning-600 dark:text-warning-500 border border-warning-50 dark:border-warning-600/30';
    case 'medium':
      return 'bg-primary-50 dark:bg-primary-600/20 text-primary-600 dark:text-primary-400 border border-primary-50 dark:border-primary-600/30';
    case 'low':
      return 'bg-success-50 dark:bg-success-600/20 text-success-600 dark:text-success-500 border border-success-50 dark:border-success-600/30';
    default:
      return 'bg-surface-100 dark:bg-surface-800 text-surface-600 dark:text-surface-400 border border-surface-200 dark:border-surface-700';
  }
}

function sortTickets(tickets: Ticket[], key: SortKey, dir: SortDir): Ticket[] {
  return [...tickets].sort((a, b) => {
    let cmp = 0;

    if (key === 'ticket_number') {
      cmp = (a.ticket_number ?? 0) - (b.ticket_number ?? 0);
    } else if (key === 'priority') {
      const wa = PRIORITY_WEIGHT[a.priority ?? ''] ?? 99;
      const wb = PRIORITY_WEIGHT[b.priority ?? ''] ?? 99;
      cmp = wa - wb;
    } else if (key === 'status') {
      const wa = STATUS_WEIGHT[a.status] ?? 99;
      const wb = STATUS_WEIGHT[b.status] ?? 99;
      cmp = wa - wb;
    } else if (key === 'created_at') {
      cmp = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
    } else {
      const av = (a[key] ?? '').toString().toLowerCase();
      const bv = (b[key] ?? '').toString().toLowerCase();
      cmp = av.localeCompare(bv);
    }

    return dir === 'asc' ? cmp : -cmp;
  });
}

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: 'ticket_number', label: '#' },
  { key: 'title', label: 'Title' },
  { key: 'status', label: 'Status' },
  { key: 'priority', label: 'Priority' },
  { key: 'device_id', label: 'Device' },
  { key: 'assigned_to', label: 'Assigned To' },
  { key: 'created_at', label: 'Created' },
];

export default function TicketTable({ tickets, loading }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('created_at');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  if (loading) {
    return <LoadingSkeleton rows={5} className="mt-4" />;
  }

  function handleHeaderClick(key: SortKey) {
    if (key === sortKey) {
      setSortDir((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  }

  const sorted = sortTickets(tickets, sortKey, sortDir);
  const arrow = sortDir === 'asc' ? '^' : 'v';

  return (
    <div className="overflow-x-auto rounded-xl border border-surface-200 dark:border-surface-800">
      <table className="w-full text-sm text-left">
        <thead className="bg-surface-100 dark:bg-surface-800 text-surface-600 dark:text-surface-400 text-xs uppercase tracking-wider">
          <tr>
            {COLUMNS.map((col) => (
              <th
                key={col.key}
                onClick={() => handleHeaderClick(col.key)}
                className="px-4 py-3 cursor-pointer select-none whitespace-nowrap hover:text-surface-900 dark:hover:text-surface-50 transition-colours"
              >
                {col.label}
                {sortKey === col.key && (
                  <span className="ml-1 opacity-60">{arrow}</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-surface-100 dark:divide-surface-800">
          {sorted.length === 0 ? (
            <tr>
              <td
                colSpan={COLUMNS.length}
                className="px-4 py-8 text-center text-surface-400 dark:text-surface-600"
              >
                No tickets found.
              </td>
            </tr>
          ) : (
            sorted.map((ticket) => (
              <tr
                key={ticket.id}
                className="bg-white dark:bg-surface-900 hover:bg-surface-50 dark:hover:bg-surface-800/60 transition-colours"
              >
                <td className="px-4 py-3 font-mono text-xs text-surface-500 dark:text-surface-400 whitespace-nowrap">
                  {formatTicketNumber(ticket.ticket_number)}
                </td>
                <td className="px-4 py-3 font-medium text-surface-800 dark:text-surface-200 max-w-xs truncate">
                  {ticket.title ?? '-'}
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${pillClasses(ticket.status)}`}
                  >
                    {ticket.status.replace('_', ' ')}
                  </span>
                </td>
                <td className="px-4 py-3">
                  {ticket.priority ? (
                    <span
                      className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${pillClasses(ticket.priority)}`}
                    >
                      {ticket.priority}
                    </span>
                  ) : (
                    <span className="text-surface-400 dark:text-surface-600">-</span>
                  )}
                </td>
                <td className="px-4 py-3 text-surface-600 dark:text-surface-400 font-mono text-xs">
                  {ticket.device_id ?? '-'}
                </td>
                <td className="px-4 py-3 text-surface-600 dark:text-surface-400">
                  {ticket.assigned_to ?? (
                    <span className="text-surface-200 dark:text-surface-600 italic">Unassigned</span>
                  )}
                </td>
                <td className="px-4 py-3 text-surface-400 dark:text-surface-600 whitespace-nowrap">
                  {formatDate(ticket.created_at)}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
