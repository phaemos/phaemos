'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';
import type { Ticket } from '@/types';
import TicketForm from '@/components/tickets/TicketForm';
import TicketTableComponent from '@/components/tickets/TicketTable';

export default function TicketsPage() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    api.get<Ticket[]>('/tickets')
      .then((r) => setTickets(r.data))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  return (
    <main className="p-6 max-w-5xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Maintenance Tickets</h1>
      <TicketForm onSuccess={load} />
      <TicketTableComponent tickets={tickets} loading={loading} />
    </main>
  );
}
