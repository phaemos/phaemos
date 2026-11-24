// the state machine behind the live readings socket, with nothing of React or the browser in it so that a test can drive it with a
// stand-in socket and a hand-wound clock. hooks/useWebSocketTelemetry.ts supplies the real socket, token and timers.
//
// The rules:
// - The access token goes in the first frame. A token that has run out is renewed before connecting.
// - The API closes a socket with 1008 when it refuses it and also when the token that opened it runs out (every 15 minutes in
//   production). A 1008 is answered with one renewal and one new socket. The allowance for that is given back as soon as a socket
//   opens, so a page can live through any number of expiries. A second 1008 with no open socket between means a real refusal.
// - A renewal the API refuses means the session is over, which is said as such.
// - Any other close is retried with a growing delay (capped, with jitter). The count of tries is only given back when a socket
//   has stayed open for STABLE_MS, so a socket the server accepts and then drops straight away does not retry for ever. After
//   MAX_TRIES the machine stops and says so.

export const BASE_MS = 1000;
export const CAP_MS = 30_000;
export const MAX_TRIES = 10;
export const STABLE_MS = 10_000;
const JITTER = 0.25;

// the wait before try number `attempt` (0 for the first): doubling from BASE_MS up to CAP_MS, then spread by up to 25 per cent
// either way so many pages that lost the same socket do not return at the same moment
export function backoffDelay(attempt: number, random: number): number {
  const base = Math.min(CAP_MS, BASE_MS * 2 ** attempt);
  return Math.round(base * (1 - JITTER + 2 * JITTER * random));
}

export type StopReason = 'session' | 'refused' | 'retries' | 'frame';

export type LiveState = { state: 'live' } | { state: 'reconnecting' } | { state: 'stopped'; why: StopReason };

export interface SocketLike {
  send(data: string): void;
  close(): void;
  onopen: (() => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onclose: ((event: { code: number }) => void) | null;
  onerror: (() => void) | null;
}

export interface LiveDeps {
  openSocket(): SocketLike;
  getToken(): string | null;
  isFresh(token: string): boolean;
  // renews the access token. Gives the new token or null when the session is over
  refresh(failed: string | null): Promise<string | null>;
  // the first frame for a token or null when it cannot be sent
  frameFor(token: string): string | null;
  onMessage(data: string): void;
  onState(state: LiveState): void;
  setTimer(fn: () => void, ms: number): unknown;
  clearTimer(handle: unknown): void;
  now(): number;
  random(): number;
}

export interface LiveSocket {
  start(): void;
  close(): void;
}

export function createLiveSocket(deps: LiveDeps): LiveSocket {
  let closed = false;
  let generation = 0;
  let current: SocketLike | null = null;
  let timer: unknown = null;
  let attempts = 0;
  let authRetried = false;
  let openedAt: number | null = null;

  const stop = (why: StopReason) => {
    if (!closed) deps.onState({ state: 'stopped', why });
  };

  async function connect(): Promise<void> {
    if (closed) return;
    const gen = generation;
    let token = deps.getToken();
    // a token that has run out would only be refused, so it is renewed first
    if (token && !deps.isFresh(token)) token = await deps.refresh(token);
    if (closed || gen !== generation) return;
    if (!token) return deps.getToken() === null ? stop('session') : retryLater();
    const frame = deps.frameFor(token);
    if (!frame) return stop('frame');

    deps.onState({ state: 'reconnecting' });
    const ws = deps.openSocket();
    current = ws;
    openedAt = null;
    const sentWith = token;

    ws.onopen = () => {
      openedAt = deps.now();
      // a socket that opened gives back the allowance for one renewal, so the next expiry is answered the same way
      authRetried = false;
      // the API closes a socket that sends nothing within 5 seconds, so the token goes first
      ws.send(frame);
      deps.onState({ state: 'live' });
    };
    ws.onmessage = (event) => {
      if (typeof event.data === 'string') deps.onMessage(event.data);
    };
    ws.onerror = () => {
      // onclose follows and decides
    };
    ws.onclose = (event) => {
      if (closed || ws !== current) return;
      current = null;
      const lived = openedAt === null ? 0 : deps.now() - openedAt;
      openedAt = null;

      if (event.code === 1008) {
        // refused or the token that opened the socket ran out. Same token again would only be refused again
        if (authRetried) return stop('refused');
        authRetried = true;
        deps.onState({ state: 'reconnecting' });
        void deps.refresh(sentWith).then((fresh) => {
          if (closed || gen !== generation) return;
          // no new token: if this browser has lost its token the session is over and if it has not the renewal only failed to
          // reach the API, which is tried again like any other drop
          if (!fresh) return deps.getToken() === null ? stop('session') : retryLater();
          if (fresh === sentWith) return stop('refused');
          void connect();
        });
        return;
      }

      if (lived >= STABLE_MS) attempts = 0;
      retryLater();
    };
  }

  // the next try after a growing wait or a stop once MAX_TRIES are used
  function retryLater(): void {
    attempts += 1;
    if (attempts > MAX_TRIES) return stop('retries');
    deps.onState({ state: 'reconnecting' });
    timer = deps.setTimer(() => void connect(), backoffDelay(attempts - 1, deps.random()));
  }

  return {
    start() {
      generation += 1;
      void connect();
    },
    close() {
      closed = true;
      generation += 1;
      if (timer !== null) deps.clearTimer(timer);
      const ws = current;
      current = null;
      // detach before closing so the close that follows is not read as a drop
      if (ws) {
        ws.onclose = null;
        ws.close();
      }
    },
  };
}
