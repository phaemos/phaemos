'use client';

// live readings for one machine over the API's socket. The reconnect and expiry rules live in lib/liveSocket.ts, which a test drives
// with a stand-in socket. This hook gives it the real socket, token and timers and closes the socket when the page or the machine
// changes (an account may hold only 5 sockets).
//
// it returns a LiveStatus for the page to show: { state: 'live' | 'reconnecting' | 'stopped', reason }. 'stopped' carries a sentence
// that says why and it is true: the session ended, the API refused the socket or the retries were used up after MAX_TRIES.
// onStatusChange still gets the finer WsStatus.

import { useEffect, useRef, useState } from 'react';
import type { Telemetry } from '../types/index';
import { buildTelemetryWsUrl, authFrame } from '../lib/wsUrl';
import { refreshAccessToken, tokenIsFresh } from '../lib/session';
import { MAX_TRIES, createLiveSocket, type LiveState, type StopReason } from '../lib/liveSocket';

export type WsStatus = 'connecting' | 'open' | 'closed' | 'auth_failed' | 'unavailable';

export type LiveStatus =
  | { state: 'live'; reason: null }
  | { state: 'reconnecting'; reason: null }
  | { state: 'stopped'; reason: string };

export const STOPPED_REASONS: Record<StopReason, string> = {
  session: 'Your session has ended, so live updates stopped. Sign in again to get them back.',
  refused: 'The API refused live updates for this machine. The page still refreshes its readings on its own.',
  retries: `Live updates stopped after ${MAX_TRIES} tries to reconnect. The page still refreshes its readings on its own.`,
  frame: 'Live updates could not start. The page still refreshes its readings on its own.',
};

export function liveStatusOf(state: LiveState): LiveStatus {
  if (state.state === 'live') return { state: 'live', reason: null };
  if (state.state === 'reconnecting') return { state: 'reconnecting', reason: null };
  return { state: 'stopped', reason: STOPPED_REASONS[state.why] };
}

function wsStatusOf(state: LiveState): WsStatus {
  if (state.state === 'live') return 'open';
  if (state.state === 'reconnecting') return 'connecting';
  return state.why === 'retries' ? 'unavailable' : 'auth_failed';
}

interface Options {
  onMessage: (reading: Telemetry) => void;
  onStatusChange?: (status: WsStatus) => void;
}

export function useWebSocketTelemetry(deviceId: string, { onMessage, onStatusChange }: Options): LiveStatus {
  const [live, setLive] = useState<LiveStatus>({ state: 'reconnecting', reason: null });
  // refs so the callbacks the caller passes can change without restarting the socket
  const onMessageRef = useRef(onMessage);
  const onStatusRef = useRef(onStatusChange);
  useEffect(() => { onMessageRef.current = onMessage; }, [onMessage]);
  useEffect(() => { onStatusRef.current = onStatusChange; }, [onStatusChange]);

  useEffect(() => {
    const socket = createLiveSocket({
      openSocket: () => new WebSocket(buildTelemetryWsUrl(deviceId)) as unknown as ReturnType<Parameters<typeof createLiveSocket>[0]['openSocket']>,
      getToken: () => (typeof window === 'undefined' ? null : localStorage.getItem('token')),
      isFresh: (token) => tokenIsFresh(token),
      refresh: (failed) => refreshAccessToken(failed),
      frameFor: authFrame,
      onMessage: (data) => {
        try {
          onMessageRef.current(JSON.parse(data) as Telemetry);
        } catch {
          // malformed frame - ignore and keep the connection open
        }
      },
      onState: (state) => {
        onStatusRef.current?.(wsStatusOf(state));
        setLive(liveStatusOf(state));
      },
      setTimer: (fn, ms) => setTimeout(fn, ms),
      clearTimer: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
      now: () => Date.now(),
      random: () => Math.random(),
    });
    socket.start();
    // close the socket on a page or machine change so it does not count against the account's 5
    return () => socket.close();
  }, [deviceId]);

  return live;
}
