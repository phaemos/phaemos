'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';
import type { Ticket } from '@/types';

export default function TicketsPage() {
  const [tickets, setTickets] = useState<Ticket[]>([]);

  useEffect(() => {
    api.get<Ticket[]>('/tickets').then((r) => setTickets(r.data));
  }, []);

  return (
    <main className="p-6 max-w-5xl mx-auto space-y-4">
      <h1 className="text-2xl font-bold">Maintenance Tickets</h1>
      <TicketTable tickets={tickets} />
    </main>
  );
}

function TicketTable({ tickets }: { tickets: Ticket[] }) {
  const statusColor: Record<string, string> = {
    open: 'text-red-400',
    in_progress: 'text-yellow-400',
    closed: 'text-green-400',
  };

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-800">
      <table className="w-full text-sm">
        <thead className="bg-gray-900 text-gray-400">
          <tr>
            {['Title', 'Priority', 'Status', 'Created'].map((h) => (
              <th key={h} className="px-4 py-3 text-left font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {tickets.map((t) => (
            <tr key={t.id} className="border-t border-gray-800 hover:bg-gray-900/40">
              <td className="px-4 py-3">{t.title}</td>
              <td className="px-4 py-3 capitalize">{t.priority ?? '-'}</td>
              <td className={`px-4 py-3 capitalize ${statusColor[t.status]}`}>
                {t.status}
              </td>
              <td className="px-4 py-3 text-gray-400">
                {new Date(t.created_at).toLocaleDateString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
