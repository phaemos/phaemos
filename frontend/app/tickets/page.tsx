'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';
import type { Ticket } from '@/types';
import TicketForm from '@/components/tickets/TicketForm';
import TicketTableComponent from '@/components/tickets/TicketTable';

const PAGE_SIZE = 20;

export default function TicketsPage() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);

  const load = (p: number) => {
    setLoading(true);
    api
      .get<Ticket[]>('/tickets', { params: { skip: (p - 1) * PAGE_SIZE, limit: PAGE_SIZE } })
      .then((r) => setTickets(r.data))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(page); }, [page]);

  return (
    <main className="p-6 max-w-5xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Maintenance Tickets</h1>
      <TicketForm onSuccess={() => load(page)} />
      <TicketTableComponent tickets={tickets} loading={loading} />

      <div className="flex items-center justify-between pt-2">
        <button
          type="button"
          disabled={page === 1}
          onClick={() => setPage((p) => p - 1)}
          className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 disabled:opacity-40 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
        >
          Previous
        </button>
        <span className="text-sm text-gray-500 dark:text-gray-400">Page {page}</span>
        <button
          type="button"
          disabled={tickets.length < PAGE_SIZE}
          onClick={() => setPage((p) => p + 1)}
          className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 disabled:opacity-40 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
        >
          Next
        </button>
      </div>
    </main>
  );
}
