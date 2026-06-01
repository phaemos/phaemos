'use client';

// I use setInterval rather than polling with setTimeout chains because setInterval
// keeps a stable cadence even if the fetch takes slightly longer than expected.

import { useState, useEffect, useCallback } from 'react';
import type { Telemetry } from '../types/index';
import api from '../lib/api';

interface UseTelemetryOptions {
  fromTs?: string;
  toTs?: string;
  limit?: number;
  nodeType?: string;
}

interface UseTelemetryResult {
  data: Telemetry[];
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useTelemetry(
  deviceId: string,
  options: UseTelemetryOptions = {},
  intervalMs: number = 5000,
): UseTelemetryResult {
  const [data, setData] = useState<Telemetry[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const { fromTs, toTs, limit = 50, nodeType } = options;

  // I extract the fetch logic into useCallback so the interval handler and the
  // manual refetch both call the exact same function without duplicating code.
  const fetchTelemetry = useCallback(async () => {
    try {
      const params: Record<string, string | number> = { limit };
      if (fromTs) params.from_ts = fromTs;
      if (toTs) params.to_ts = toTs;
      if (nodeType) params.node_type = nodeType;
      const response = await api.get<Telemetry[]>(`/telemetry/${deviceId}`, { params });
      setData(response.data);
      setError(null);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to fetch telemetry';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [deviceId, fromTs, toTs, limit, nodeType]);

  useEffect(() => {
    // I set loading true whenever the deviceId or time range changes so the consumer
    // knows fresh data is incoming rather than displaying stale results.
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
