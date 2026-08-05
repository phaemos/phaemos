'use client';

// I follow the same polling pattern as useTelemetry so both hooks behave
// consistently and operators see near-real-time alert state without a manual
// page refresh.

import { useState, useEffect, useCallback } from 'react';
import type { Alert } from '../types/index';
import api from '../lib/api';

interface UseAlertsResult {
  data: Alert[];
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useAlerts(intervalMs: number = 5000): UseAlertsResult {
  const [data, setData] = useState<Alert[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // I only fetch unresolved alerts here because the dashboard alert panel
  // is an active-issues feed - resolved alerts belong in a separate history view.
  const fetchAlerts = useCallback(async () => {
    try {
      const response = await api.get<Alert[]>('/alerts', {
        params: { resolved: false },
      });
      setData(response.data);
      setError(null);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to fetch alerts';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Fetching on mount/dependency change, the documented effect pattern
    // (react.dev/learn/synchronizing-with-effects#fetching-data).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    fetchAlerts();

    const intervalId = setInterval(fetchAlerts, intervalMs);

    // I clear the interval so the hook does not keep firing after the component
    // that called it has been removed from the tree.
    return () => {
      clearInterval(intervalId);
    };
  }, [intervalMs, fetchAlerts]);

  return { data, loading, error, refetch: fetchAlerts };
}
