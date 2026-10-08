'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';
import type { Device, Ticket } from '@/types';
import TicketForm from '@/components/tickets/TicketForm';
import TicketTableComponent from '@/components/tickets/TicketTable';
import Card from '@/components/ui/Card';
import PageHeader from '@/components/ui/PageHeader';

const PAGE_SIZE = 20;

export default function TicketsPage() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [deviceNames, setDeviceNames] = useState<Record<string, string>>({});
  const [creating, setCreating] = useState(false);

  const load = (p: number) => {
    setLoading(true);
    api
      .get<Ticket[]>('/tickets', { params: { skip: (p - 1) * PAGE_SIZE, limit: PAGE_SIZE } })
      .then((r) => setTickets(r.data))
      .finally(() => setLoading(false));
  };

  // fetching on mount/dependency change, the documented effect pattern
  // (react.dev/learn/synchronizing-with-effects#fetching-data).
  useEffect(() => { load(page); }, [page]); // eslint-disable-line react-hooks/set-state-in-effect

  // tickets store a device id, so the table names each machine from the device list
  useEffect(() => {
    api.get<Device[]>('/devices')
      .then((r) => setDeviceNames(Object.fromEntries(r.data.map((d) => [d.id, d.name]))))
      .catch(() => {});
  }, []);

  return (
    <main className="mx-auto max-w-6xl space-y-6 p-6">
      <PageHeader
        title="Maintenance tickets"
        description="Work raised by people and by the anomaly model, newest first."
        actions={
          <button type="button" onClick={() => setCreating((c) => !c)} aria-expanded={creating}
            className="rounded-lg bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700">
            {creating ? 'Close' : 'New ticket'}
          </button>
        }
      />
      {creating && (
        <Card title="New ticket">
          <TicketForm onSuccess={() => { setCreating(false); load(page); }} />
        </Card>
      )}
      <Card bodyClassName="">
        <TicketTableComponent tickets={tickets} loading={loading} deviceNames={deviceNames} />
      </Card>

      <div className="flex items-center justify-between pt-2">
        <button
          type="button"
          disabled={page === 1}
          onClick={() => setPage((p) => p - 1)}
          className="bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700 text-surface-900 dark:text-surface-50 px-4 py-2 rounded-lg text-sm font-medium transition-colors duration-150 disabled:opacity-40"
        >
          Previous
        </button>
        <span className="text-sm text-surface-600 dark:text-surface-400">Page {page}</span>
        <button
          type="button"
          disabled={tickets.length < PAGE_SIZE}
          onClick={() => setPage((p) => p + 1)}
          className="bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700 text-surface-900 dark:text-surface-50 px-4 py-2 rounded-lg text-sm font-medium transition-colors duration-150 disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </main>
  );
}
