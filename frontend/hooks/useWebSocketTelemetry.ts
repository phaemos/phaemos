'use client';

// I use exponential backoff rather than a fixed retry interval because the
// server may be temporarily overloaded - hammering it every second makes that worse.
// I skip all retries on close code 1008 (auth failure) to avoid an infinite
// loop where an expired or invalid token triggers endless reconnect attempts.

import { useEffect, useRef, useCallback } from 'react';
import type { Telemetry } from '../types/index';

const BACKOFF_DELAYS_MS = [1000, 2000, 4000, 8000, 16000];

function buildWsUrl(deviceId: string, token: string): string {
  const base = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
  // I swap the scheme so the WS connection uses the same host/port as the REST API.
  const wsBase = base.replace(/^http/, 'ws');
  return `${wsBase}/api/v1/ws/telemetry/${deviceId}?token=${encodeURIComponent(token)}`;
}

export type WsStatus = 'connecting' | 'open' | 'closed' | 'auth_failed' | 'unavailable';

interface Options {
  onMessage: (reading: Telemetry) => void;
  onStatusChange?: (status: WsStatus) => void;
}

export function useWebSocketTelemetry(deviceId: string, { onMessage, onStatusChange }: Options): void {
  // I hold refs instead of state so reconnect logic can read current values
  // without triggering re-renders and without going stale in closure scope.
  const wsRef = useRef<WebSocket | null>(null);
  const attemptRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const destroyedRef = useRef(false);

  const onMessageRef = useRef(onMessage);
  const onStatusRef = useRef(onStatusChange);
  useEffect(() => { onMessageRef.current = onMessage; }, [onMessage]);
  useEffect(() => { onStatusRef.current = onStatusChange; }, [onStatusChange]);

  const connect = useCallback(() => {
    if (destroyedRef.current) return;

    const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
    if (!token) return;

    onStatusRef.current?.('connecting');

    const ws = new WebSocket(buildWsUrl(deviceId, token));
    wsRef.current = ws;

    ws.onopen = () => {
      attemptRef.current = 0;
      onStatusRef.current?.('open');
    };

    ws.onmessage = (event: MessageEvent) => {
      try {
        const reading = JSON.parse(event.data as string) as Telemetry;
        onMessageRef.current(reading);
      } catch {
        // malformed frame - ignore and keep connection open
      }
    };

    ws.onclose = (event: CloseEvent) => {
      wsRef.current = null;
      if (destroyedRef.current) return;

      // 1008 = Policy Violation (JWT auth failure) - retrying is pointless.
      if (event.code === 1008) {
        onStatusRef.current?.('auth_failed');
        return;
      }

      const attempt = attemptRef.current;
      if (attempt >= BACKOFF_DELAYS_MS.length) {
        onStatusRef.current?.('unavailable');
        return;
      }

      onStatusRef.current?.('closed');
      const delay = BACKOFF_DELAYS_MS[attempt];
      attemptRef.current = attempt + 1;
      // connect is referenced before its own const finishes initializing here,
      // but this callback only runs once the WebSocket actually closes, long
      // after connect's declaration has completed, so the closure always sees
      // the fully assigned function. Standard recursive-reconnect pattern.
      // eslint-disable-next-line react-hooks/immutability
      timerRef.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      // onerror always fires before onclose; let onclose handle the retry logic.
    };
  }, [deviceId]);

  useEffect(() => {
    destroyedRef.current = false;
    attemptRef.current = 0;
    connect();

    return () => {
      destroyedRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [connect]);
}
