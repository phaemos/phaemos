import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createLiveSocket, backoffDelay, MAX_TRIES, STABLE_MS, CAP_MS, type LiveState, type SocketLike } from './liveSocket.ts';

// a stand-in socket and a clock the test winds by hand
function rig(options: { refresh?: (failed: string | null) => Promise<string | null>; } = {}) {
  let clock = 0;
  const timers: { at: number; fn: () => void; id: number }[] = [];
  let nextId = 1;
  const sockets: (SocketLike & { sent: string[]; closedByUs: boolean })[] = [];
  const states: LiveState[] = [];
  let token: string | null = 'tok-0';
  let renewals = 0;
  const deps = {
    openSocket() {
      const s = { sent: [] as string[], closedByUs: false, onopen: null, onmessage: null, onclose: null, onerror: null, send(d: string) { this.sent.push(d); }, close() { this.closedByUs = true; } } as unknown as SocketLike & { sent: string[]; closedByUs: boolean };
      sockets.push(s);
      return s;
    },
    getToken: () => token,
    isFresh: () => true,
    // a refusal by the API ends the session, which takes the token with it. A failure to reach the API leaves the token
    refresh: options.refresh ?? (async () => { renewals += 1; token = `tok-${renewals}`; return token; }),
    frameFor: (t: string) => JSON.stringify({ type: 'auth', token: t }),
    onMessage() {},
    onState: (s: LiveState) => states.push(s),
    setTimer: (fn: () => void, ms: number) => { const id = nextId++; timers.push({ at: clock + ms, fn, id }); return id; },
    clearTimer: (h: unknown) => { const i = timers.findIndex((t) => t.id === h); if (i >= 0) timers.splice(i, 1); },
    now: () => clock,
    random: () => 0.5,
  };
  const live = createLiveSocket(deps);
  const tick = async () => { for (let i = 0; i < 5; i++) await Promise.resolve(); };
  const last = () => sockets[sockets.length - 1];
  return {
    setToken: (t: string | null) => { token = t; },
    live, sockets, states, last, tick,
    advance: async (ms: number) => { clock += ms; for (const t of timers.filter((x) => x.at <= clock)) { timers.splice(timers.indexOf(t), 1); t.fn(); } await tick(); },
    state: () => states[states.length - 1],
  };
}

test('it stays live through ten token expiries when each renewal succeeds', async () => {
  const r = rig();
  r.live.start();
  await r.tick();
  for (let i = 0; i < 10; i++) {
    r.last().onopen?.();
    assert.equal(r.state().state, 'live');
    await r.advance(15 * 60 * 1000);
    // the API closes the socket with 1008 when its token runs out
    r.last().onclose?.({ code: 1008 });
    await r.tick();
    assert.equal(r.sockets.length, i + 2, 'a new socket follows each expiry');
  }
  r.last().onopen?.();
  assert.equal(r.state().state, 'live');
  // each socket sent its own fresh token in the first frame
  assert.equal(JSON.parse(r.sockets[3].sent[0]).token, 'tok-3');
});

test('a renewal the API refuses stops it with the true reason', async () => {
  const r = rig({ refresh: async () => null });
  r.live.start();
  await r.tick();
  r.last().onopen?.();
  // the API refused the renewal, which ends the session and clears the token
  r.setToken(null);
  r.last().onclose?.({ code: 1008 });
  await r.tick();
  assert.deepEqual(r.state(), { state: 'stopped', why: 'session' });
  assert.equal(r.sockets.length, 1, 'no further socket');
});

test('a refusal that comes straight back is a real refusal and is not retried in a loop', async () => {
  const r = rig();
  r.live.start();
  await r.tick();
  r.last().onclose?.({ code: 1008 }); // refused before it ever opened
  await r.tick();
  assert.equal(r.sockets.length, 2);
  r.last().onclose?.({ code: 1008 }); // refused again with no open socket between
  await r.tick();
  assert.deepEqual(r.state(), { state: 'stopped', why: 'refused' });
  assert.equal(r.sockets.length, 2);
});

test('a socket that opens and is dropped at once is retried with a growing delay and then stopped', async () => {
  const r = rig();
  r.live.start();
  await r.tick();
  const waits: number[] = [];
  for (let i = 0; i < MAX_TRIES; i++) {
    r.last().onopen?.();
    await r.advance(100);
    r.last().onclose?.({ code: 1006 });
    waits.push(backoffDelay(i, 0.5));
    await r.advance(CAP_MS * 2);
  }
  r.last().onopen?.();
  r.last().onclose?.({ code: 1006 });
  await r.tick();
  assert.deepEqual(r.state(), { state: 'stopped', why: 'retries' });
  assert.ok(waits[1] > waits[0] && waits[5] > waits[2], 'the wait grows');
  assert.ok(waits.every((w) => w <= CAP_MS * 1.25), 'and is capped');
});

test('a socket that stayed open gives its tries back', async () => {
  const r = rig();
  r.live.start();
  await r.tick();
  for (let i = 0; i < MAX_TRIES * 3; i++) {
    r.last().onopen?.();
    await r.advance(STABLE_MS + 1000);
    r.last().onclose?.({ code: 1006 });
    await r.advance(CAP_MS * 2);
  }
  r.last().onopen?.();
  assert.equal(r.state().state, 'live');
});

test('the delay doubles, is capped and is spread by jitter', () => {
  assert.equal(backoffDelay(0, 0.5), 1000);
  assert.equal(backoffDelay(1, 0.5), 2000);
  assert.equal(backoffDelay(10, 0.5), CAP_MS);
  assert.equal(backoffDelay(0, 0), 750);
  assert.equal(backoffDelay(0, 1), 1250);
});

test('closing it closes the socket and nothing more happens', async () => {
  const r = rig();
  r.live.start();
  await r.tick();
  const ws = r.last();
  ws.onopen?.();
  r.live.close();
  assert.equal(ws.closedByUs, true);
  await r.advance(60_000);
  assert.equal(r.sockets.length, 1);
});

test('a renewal that could not reach the API is tried again and is not called a refusal', async () => {
  const r = rig({ refresh: async () => null });
  r.live.start();
  await r.tick();
  r.last().onopen?.();
  r.last().onclose?.({ code: 1008 });
  await r.tick();
  assert.equal(r.state().state, 'reconnecting');
  await r.advance(CAP_MS * 2);
  assert.equal(r.sockets.length, 2, 'it opens a new socket and does not stop');
});
