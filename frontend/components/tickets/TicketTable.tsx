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

type SortKey = 'title' | 'status' | 'priority' | 'device_id' | 'assigned_to' | 'created_at';
type SortDir = 'asc' | 'desc';

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
      return 'bg-blue-900/50 text-blue-300 border border-blue-700';
    case 'in_progress':
      return 'bg-amber-900/50 text-amber-300 border border-amber-700';
    case 'closed':
      return 'bg-gray-700 text-gray-400 border border-gray-600';
    case 'critical':
      return 'bg-red-900/50 text-red-300 border border-red-700';
    case 'high':
      return 'bg-orange-900/50 text-orange-300 border border-orange-700';
    case 'medium':
      return 'bg-yellow-900/50 text-yellow-300 border border-yellow-700';
    case 'low':
      return 'bg-green-900/50 text-green-300 border border-green-700';
    default:
      return 'bg-gray-700 text-gray-400 border border-gray-600';
  }
}

function sortTickets(
  tickets: Ticket[],
  key: SortKey,
  dir: SortDir,
): Ticket[] {
  return [...tickets].sort((a, b) => {
    let cmp = 0;

    if (key === 'priority') {
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
    <div className="overflow-x-auto rounded-xl border border-gray-700">
      <table className="w-full text-sm text-left">
        <thead className="bg-gray-800 text-gray-400 text-xs uppercase tracking-wider">
          <tr>
            {COLUMNS.map((col) => (
              <th
                key={col.key}
                onClick={() => handleHeaderClick(col.key)}
                className="px-4 py-3 cursor-pointer select-none whitespace-nowrap hover:text-gray-200 transition-colors"
              >
                {col.label}
                {sortKey === col.key && (
                  <span className="ml-1 opacity-60">{arrow}</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-700">
          {sorted.length === 0 ? (
            <tr>
              <td
                colSpan={COLUMNS.length}
                className="px-4 py-8 text-center text-gray-500"
              >
                No tickets found.
              </td>
            </tr>
          ) : (
            sorted.map((ticket) => (
              <tr
                key={ticket.id}
                className="bg-gray-900 hover:bg-gray-800/60 transition-colors"
              >
                <td className="px-4 py-3 font-medium text-gray-200 max-w-xs truncate">
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
                    <span className="text-gray-500">-</span>
                  )}
                </td>
                <td className="px-4 py-3 text-gray-400 font-mono text-xs">
                  {ticket.device_id ?? '-'}
                </td>
                <td className="px-4 py-3 text-gray-400">
                  {ticket.assigned_to ?? (
                    <span className="text-gray-600 italic">Unassigned</span>
                  )}
                </td>
                <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
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
