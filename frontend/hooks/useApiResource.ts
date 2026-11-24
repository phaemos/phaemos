'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import api from '@/lib/api';
import { describeApiError } from '@/lib/apiError';
import { requestIdOf } from '@/lib/apiCode';
import { noteResponse } from '@/lib/serverClock';

export interface ApiResource<T> {
  data: T | null;
  // a plain sentence or null. Show it with ErrorNotice in place of an empty state.
  error: string | null;
  // the request_id the API put on the error, for a person to quote. Null when there was none.
  errorRef: string | null;
  // true while the rows shown are the last answer to an earlier request (only with keepPrevious): the new one has not come yet
  stale: boolean;
  // true until the first answer for this path and params and again while retry runs
  loading: boolean;
  retry: () => void;
  // the X-Total-Count header when the API sent one: how many rows exist beyond the limit asked for
  total: number | null;
  // when the last answer that succeeded arrived (milliseconds) or null before the first
  updatedAt: number | null;
}

interface Options {
  params?: Record<string, string | number | boolean | undefined>;
  // poll on this interval in milliseconds. Polling never sets loading, so a list does not flash.
  intervalMs?: number;
  // what the thing is called in the error sentence: "The machines"
  what?: string;
  // pass false to wait, for example until an id is known
  enabled?: boolean;
  // when the path or params change, keep showing the last answer until the new one lands, instead of going back to nothing
  keepPrevious?: boolean;
}

interface State<T> {
  key: string;
  attempt: number;
  data: T | null;
  error: string | null;
  errorRef?: string | null;
  total: number | null;
  updatedAt: number | null;
}

// a request that has not answered by now is given up, so a slow API cannot hold a poll open for ever
const TIMEOUT_MS = 20_000;

function readTotal(headers: unknown): number | null {
  const raw = (headers as { get?: (name: string) => unknown } | undefined)?.get?.('x-total-count') ?? (headers as Record<string, unknown> | undefined)?.['x-total-count'];
  const n = typeof raw === 'string' ? Number(raw) : typeof raw === 'number' ? raw : Number.NaN;
  return Number.isInteger(n) && n >= 0 ? n : null;
}

// reads one GET endpoint through lib/api.ts, so the token, the refresh on 401 and the base URL stay in one place;
// it returns { data, error, loading, retry, total, updatedAt }. Data from an earlier success is kept when a later poll
// fails, so an error appears beside the stale list and not instead of it.
//
// polling is polite: a tick is skipped while the last request is still in flight (a slow API never piles up reads) and
// while the tab is hidden. The tab's return fetches at once.
export function useApiResource<T>(path: string | null, { params, intervalMs, what, enabled = true, keepPrevious = false }: Options = {}): ApiResource<T> {
  const key = `${path ?? ''}?${JSON.stringify(params ?? {})}`;
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<State<T> | null>(null);
  // the latest options live in a ref so an inline params object does not restart the effect on every render
  const latest = useRef({ params, what });
  useEffect(() => {
    latest.current = { params, what };
  });

  useEffect(() => {
    if (!path || !enabled) return;
    let alive = true;
    let inFlight = false;
    const controller = new AbortController();
    const load = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const sentAt = Date.now();
        const res = await api.get<T>(path, { params: latest.current.params, timeout: TIMEOUT_MS, signal: controller.signal });
        // every ordinary answer also tells the page what time the server thinks it is
        noteResponse(res.headers as never, res.data, sentAt, Date.now());
        if (alive) setState({ key, attempt, data: res.data, error: null, total: readTotal(res.headers), updatedAt: Date.now() });
      } catch (err) {
        if (alive) setState((prev) => ({ key, attempt, data: prev && prev.key === key ? prev.data : null, error: describeApiError(err, latest.current.what), errorRef: requestIdOf(err) ?? null, total: prev && prev.key === key ? prev.total : null, updatedAt: prev && prev.key === key ? prev.updatedAt : null }));
      } finally {
        inFlight = false;
      }
    };
    load();
    if (!intervalMs) {
      return () => {
        alive = false;
        controller.abort();
      };
    }
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') load();
    }, intervalMs);
    const onVisible = () => {
      if (document.visibilityState === 'visible') load();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      alive = false;
      controller.abort();
      clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [path, key, attempt, intervalMs, enabled]);

  const retry = useCallback(() => setAttempt((a) => a + 1), []);

  const current = state && state.key === key ? state : null;
  const shown = current ?? (keepPrevious && state ? state : null);
  const loading = enabled && path !== null && (current === null || current.attempt !== attempt);
  return { data: shown?.data ?? null, error: current?.error ?? null, errorRef: current?.errorRef ?? null, stale: current === null && shown !== null, loading: loading && !(keepPrevious && shown !== null), retry, total: shown?.total ?? null, updatedAt: shown?.updatedAt ?? null };
}
