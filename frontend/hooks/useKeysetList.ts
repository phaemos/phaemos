'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import api from '@/lib/api';
import { describeApiError } from '@/lib/apiError';
import { requestIdOf } from '@/lib/apiCode';
import { noteResponse } from '@/lib/serverClock';
import { mergeFirstPage, nextCursor } from '@/lib/keyset';

interface Options<T> {
  params?: Record<string, string | number | boolean | undefined>;
  pageSize: number;
  // the cursor position of a row, `<ISO time>,<id>` as the API writes it in X-Next-Before. It is how a refreshed first page is joined to the
  // older pages already loaded.
  cursorOf: (item: T) => string;
  intervalMs?: number;
  what?: string;
  enabled?: boolean;
}

export interface KeysetList<T> {
  items: T[];
  error: string | null;
  errorRef: string | null;
  // true until the first page answers
  loading: boolean;
  loadingMore: boolean;
  // false once a page has come back short
  hasMore: boolean;
  loadMore: () => void;
  retry: () => void;
  // X-Total-Count of the first page when the route sends one
  total: number | null;
  updatedAt: number | null;
}

interface State<T> {
  key: string;
  items: T[];
  cursor: string | null;
  done: boolean;
  total: number | null;
  updatedAt: number;
}

// a list read by keyset paging: the first page, then `before=<cursor>` for each older page until one comes back short. A row that
// arrives live goes to the front and cannot shift the pages already read. The first page is refreshed on an interval and joined to the
// older pages (lib/keyset.ts), so a row that has left the list (an alert resolved) leaves it and no row is ever listed twice.
export function useKeysetList<T extends { id: string }>(path: string, { params, pageSize, cursorOf, intervalMs, what, enabled = true }: Options<T>): KeysetList<T> {
  const key = `${path}?${JSON.stringify(params ?? {})}`;
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<State<T> | null>(null);
  const [error, setError] = useState<{ key: string; text: string; ref: string | null } | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const latest = useRef({ params, cursorOf, what, state });
  useEffect(() => {
    latest.current = { params, cursorOf, what, state };
  });

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    let inFlight = false;
    const controller = new AbortController();
    const load = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const sentAt = Date.now();
        const res = await api.get<T[]>(path, { params: { ...latest.current.params, limit: pageSize }, timeout: 20_000, signal: controller.signal });
        noteResponse(res.headers as never, res.data, sentAt, Date.now());
        if (!alive) return;
        const page = Array.isArray(res.data) ? res.data : [];
        const header = (res.headers as { get?: (n: string) => unknown } | undefined)?.get?.('x-next-before');
        const total = Number((res.headers as { get?: (n: string) => unknown } | undefined)?.get?.('x-total-count'));
        setState((prev) => {
          const old = prev && prev.key === key ? prev : null;
          const merged = old ? mergeFirstPage(page, old.items, latest.current.cursorOf, pageSize) : null;
          const keep = Boolean(merged && merged.keptOlder && old);
          return {
            key,
            items: merged ? merged.items : page,
            cursor: keep && old ? old.cursor : nextCursor(header, page.length, pageSize),
            done: keep && old ? old.done : page.length < pageSize,
            total: Number.isInteger(total) && total >= 0 ? total : old?.total ?? null,
            updatedAt: Date.now(),
          };
        });
        setError(null);
      } catch (err) {
        if (alive) setError({ key, text: describeApiError(err, latest.current.what), ref: requestIdOf(err) ?? null });
      } finally {
        inFlight = false;
      }
    };
    load();
    if (!intervalMs) return () => { alive = false; controller.abort(); };
    const id = setInterval(() => { if (document.visibilityState === 'visible') load(); }, intervalMs);
    return () => { alive = false; controller.abort(); clearInterval(id); };
  }, [path, key, attempt, intervalMs, enabled, pageSize]);

  const loadMore = useCallback(async () => {
    const cur = latest.current.state;
    if (!cur || cur.key !== key || cur.done || !cur.cursor) return;
    setLoadingMore(true);
    try {
      const res = await api.get<T[]>(path, { params: { ...latest.current.params, limit: pageSize, before: cur.cursor }, timeout: 20_000 });
      const page = Array.isArray(res.data) ? res.data : [];
      const header = (res.headers as { get?: (n: string) => unknown } | undefined)?.get?.('x-next-before');
      setState((prev) => {
        if (!prev || prev.key !== key) return prev;
        const have = new Set(prev.items.map((i) => i.id));
        return { ...prev, items: [...prev.items, ...page.filter((i) => !have.has(i.id))], cursor: nextCursor(header, page.length, pageSize), done: page.length < pageSize };
      });
      setError(null);
    } catch (err) {
      setError({ key, text: describeApiError(err, latest.current.what), ref: requestIdOf(err) ?? null });
    } finally {
      setLoadingMore(false);
    }
  }, [key, path, pageSize]);

  const retry = useCallback(() => setAttempt((a) => a + 1), []);
  const cur = state && state.key === key ? state : null;
  const err = error && error.key === key ? error : null;
  return { items: cur?.items ?? [], error: err?.text ?? null, errorRef: err?.ref ?? null, loading: enabled && cur === null && err === null, loadingMore, hasMore: cur ? !cur.done : false, loadMore, retry, total: cur?.total ?? null, updatedAt: cur?.updatedAt ?? null };
}
