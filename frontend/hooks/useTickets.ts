'use client';

// I poll on an interval rather than fetching once so the ticket list stays
// current when other users create or update tickets during a long-running session.

import { useState, useEffect, useCallback } from 'react';
import type { Ticket } from '../types/index';
import api from '../lib/api';

interface UseTicketsResult {
  data: Ticket[];
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useTickets(
  status?: string,
  intervalMs: number = 5000,
): UseTicketsResult {
  const [data, setData]       = useState<Ticket[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError]     = useState<string | null>(null);

  const fetchTickets = useCallback(async () => {
    try {
      const params: Record<string, string> = {};
      // I only add the status param when it is provided so a missing value
      // does not send ?status=undefined to the API.
      if (status) params.status = status;

      const response = await api.get<Ticket[]>('/tickets', { params });
      setData(response.data);
      setError(null);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to fetch tickets';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    // Fetching on mount/dependency change, the documented effect pattern
    // (react.dev/learn/synchronizing-with-effects#fetching-data).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    fetchTickets();
    const id = setInterval(fetchTickets, intervalMs);
    return () => clearInterval(id);
  }, [status, intervalMs, fetchTickets]);

  return { data, loading, error, refetch: fetchTickets };
}
