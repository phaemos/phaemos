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
      <h1 className="text-2xl font-bold text-surface-900 dark:text-surface-50">Maintenance Tickets</h1>
      <TicketForm onSuccess={() => load(page)} />
      <TicketTableComponent tickets={tickets} loading={loading} />

      <div className="flex items-center justify-between pt-2">
        <button
          type="button"
          disabled={page === 1}
          onClick={() => setPage((p) => p - 1)}
          className="bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700 text-surface-900 dark:text-surface-50 px-4 py-2 rounded-lg text-sm font-medium transition-colours duration-150 disabled:opacity-40"
        >
          Previous
        </button>
        <span className="text-sm text-surface-600 dark:text-surface-400">Page {page}</span>
        <button
          type="button"
          disabled={tickets.length < PAGE_SIZE}
          onClick={() => setPage((p) => p + 1)}
          className="bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700 text-surface-900 dark:text-surface-50 px-4 py-2 rounded-lg text-sm font-medium transition-colours duration-150 disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </main>
  );
}
