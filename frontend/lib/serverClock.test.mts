// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { noteResponse, noteServerTime, resetServerClock, serverNow, serverOffsetMs } from './serverClock.ts';

const SERVER = Date.parse('2026-11-22T12:00:00Z');

// a browser whose clock is `skew` ms off the server's takes 200 ms to get an answer
function sampleWith(skew: number, headers?: Record<string, string>, data?: unknown) {
  const sent = SERVER + skew;
  noteResponse(headers, data, sent, sent + 200);
}

for (const skew of [20_000, -20_000, 300_000, -300_000, 2 * 3_600_000, -2 * 3_600_000]) {
  test(`a browser clock ${skew / 1000} s off is corrected from the Date header`, () => {
    resetServerClock();
    // the server said 12:00:00.100 (cut to 12:00:00) at the middle of the round trip
    for (let i = 0; i < 3; i += 1) sampleWith(skew - 100, { date: new Date(SERVER).toUTCString() });
    const browser = SERVER + 60_000 + skew;
    assert.ok(Math.abs(serverNow(browser) - (SERVER + 60_000)) < 1500, `corrected within a second and a half for ${skew}`);
    assert.ok(Math.abs(serverOffsetMs() + skew) < 1500);
  });

  test(`a browser clock ${skew / 1000} s off is corrected from a machine read when no Date header can be read`, () => {
    resetServerClock();
    // last post 40 s ago on the server's clock
    const device = { last_seen: new Date(SERVER - 40_000).toISOString(), seconds_since_last_post: 40 };
    for (let i = 0; i < 3; i += 1) sampleWith(skew - 100, undefined, [device]);
    assert.ok(Math.abs(serverNow(SERVER + skew) - SERVER) < 1500);
  });
}

test('with no sample the browser clock is used and a response with neither source is ignored', () => {
  resetServerClock();
  assert.equal(serverOffsetMs(), 0);
  assert.equal(serverNow(1234), 1234);
  noteResponse({}, { id: 'x' }, 0, 100);
  noteResponse(undefined, [{ last_seen: null, seconds_since_last_post: null }], 0, 100);
  assert.equal(serverOffsetMs(), 0);
  noteServerTime(Number.NaN, 0, 1);
  assert.equal(serverOffsetMs(), 0);
});

test('one slow response cannot move the estimate and Headers objects are read too', () => {
  resetServerClock();
  for (let i = 0; i < 5; i += 1) noteServerTime(SERVER + 100_000, SERVER, SERVER + 200);
  noteServerTime(SERVER + 100_000 + 90_000, SERVER, SERVER + 200);
  assert.ok(Math.abs(serverOffsetMs() - 99_900) < 200);
  resetServerClock();
  const headers = new Headers({ date: new Date(SERVER + 5000).toUTCString() });
  noteResponse(headers as unknown as { get: (n: string) => unknown }, null, SERVER, SERVER + 100);
  assert.ok(Math.abs(serverOffsetMs() - 5450) < 100);
});
