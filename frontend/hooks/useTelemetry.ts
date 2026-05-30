'use client';

// I use setInterval rather than polling with setTimeout chains because setInterval
// keeps a stable cadence even if the fetch takes slightly longer than expected.

import { useState, useEffect, useCallback } from 'react';
import type { Telemetry } from '../types/index';
import api from '../lib/api';

interface UseTelemetryResult {
  data: Telemetry[];
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useTelemetry(
  deviceId: string,
  intervalMs: number = 5000,
): UseTelemetryResult {
  const [data, setData] = useState<Telemetry[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // I extract the fetch logic into useCallback so the interval handler and the
  // manual refetch both call the exact same function without duplicating code.
  const fetchTelemetry = useCallback(async () => {
    try {
      const response = await api.get<Telemetry[]>('/telemetry', {
        params: { device_id: deviceId, limit: 50 },
      });
      setData(response.data);
      setError(null);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to fetch telemetry';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [deviceId]);

  useEffect(() => {
    // I set loading true whenever the deviceId changes so the consumer knows
    // fresh data is incoming rather than displaying stale results.
    setLoading(true);
    fetchTelemetry();

    const intervalId = setInterval(fetchTelemetry, intervalMs);

    // I clear the interval on cleanup to prevent stale closures from updating
    // state after the component that owns this hook has unmounted.
    return () => {
      clearInterval(intervalId);
    };
  }, [deviceId, intervalMs, fetchTelemetry]);

  return { data, loading, error, refetch: fetchTelemetry };
}
