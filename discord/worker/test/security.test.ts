import assert from "node:assert/strict";
import { test } from "node:test";
import { MAX_BODY_BYTES } from "../src/app.ts";
import { Harness, PUBLIC_KEY, content, makeEnv, signBody } from "./helpers.ts";

const PING = JSON.stringify({ type: 1 });

test("a ping with a valid signature is answered with a pong", async () => {
  const h = new Harness();
  const res = await h.app.fetch(h.signedRequest(PING), h.env, h.ctx);
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("content-type"), "application/json");
  assert.deepEqual(await res.json(), { type: 1 });
});

test("a bad signature gets 401", async () => {
  const h = new Harness();
  const ts = String(Math.floor(h.clock / 1000));
  for (const signature of [signBody(ts, PING, true), "zz".repeat(64), "ab".repeat(10), "", "00".repeat(64)]) {
    const res = await h.app.fetch(h.signedRequest(PING, { signature }), h.env, h.ctx);
    assert.equal(res.status, 401, `signature ${signature.slice(0, 8)}`);
  }
});

test("a missing signature or timestamp gets 401", async () => {
  const h = new Harness();
  const bare = new Request("https://worker.example/interactions", { method: "POST", body: PING });
  assert.equal((await h.app.fetch(bare, h.env, h.ctx)).status, 401);
  const noTs = new Request("https://worker.example/interactions", {
    method: "POST",
    body: PING,
    headers: { "x-signature-ed25519": signBody("1", PING) },
  });
  assert.equal((await h.app.fetch(noTs, h.env, h.ctx)).status, 401);
});

test("a replayed body with a changed timestamp gets 401", async () => {
  const h = new Harness();
  const ts = String(Math.floor(h.clock / 1000));
  const signature = signBody(ts, PING);
  const later = String(Number(ts) + 1);
  const res = await h.app.fetch(h.signedRequest(PING, { signature, timestamp: later }), h.env, h.ctx);
  assert.equal(res.status, 401);
});

test("a correctly signed body that is too old or too far ahead gets 401", async () => {
  const h = new Harness();
  const now = Math.floor(h.clock / 1000);
  for (const ts of [String(now - 3600), String(now - 301), String(now + 301), "0"]) {
    const res = await h.app.fetch(h.signedRequest(PING, { timestamp: ts }), h.env, h.ctx);
    assert.equal(res.status, 401, `timestamp offset ${Number(ts) - now}`);
  }
  const edge = await h.app.fetch(h.signedRequest(PING, { timestamp: String(now - 299) }), h.env, h.ctx);
  assert.equal(edge.status, 200);
});

test("a non-numeric timestamp gets 401", async () => {
  const h = new Harness();
  for (const ts of ["abc", "1e9", "-5", " 12", "9".repeat(30)]) {
    const res = await h.app.fetch(
      h.signedRequest(PING, { timestamp: ts, signature: signBody(ts, PING) }),
      h.env,
      h.ctx,
    );
    assert.equal(res.status, 401, ts);
  }
});

test("a huge body is refused with 413 whatever its signature", async () => {
  const h = new Harness();
  const huge = JSON.stringify({ type: 1, pad: "x".repeat(MAX_BODY_BYTES + 10) });
  const res = await h.app.fetch(h.signedRequest(huge), h.env, h.ctx);
  assert.equal(res.status, 413);
  const unsigned = await h.app.fetch(h.signedRequest(huge, { signature: "00".repeat(64) }), h.env, h.ctx);
  assert.equal(unsigned.status, 413);
});

test("a body just inside the limit still verifies", async () => {
  const h = new Harness();
  const pad = "x".repeat(MAX_BODY_BYTES - 40);
  const res = await h.app.fetch(h.signedRequest(JSON.stringify({ type: 1, pad })), h.env, h.ctx);
  assert.equal(res.status, 200);
});

test("a declared length over the limit is refused before the body is read", async () => {
  const h = new Harness();
  const req = h.signedRequest(PING);
  const forged = new Request(req.url, {
    method: "POST",
    headers: { ...Object.fromEntries(req.headers), "content-length": String(MAX_BODY_BYTES + 1) },
    body: PING,
  });
  assert.equal((await h.app.fetch(forged, h.env, h.ctx)).status, 413);
});

test("garbage is refused with 401 and nothing is parsed", async () => {
  const h = new Harness();
  const garbage = "{{{ not json \u0000\u0001";
  const res = await h.app.fetch(h.signedRequest(garbage, { signature: "11".repeat(64) }), h.env, h.ctx);
  assert.equal(res.status, 401);
  const binary = new Uint8Array([0, 255, 254, 1, 2, 3]);
  const res2 = await h.app.fetch(h.signedRequest(binary, { signature: "22".repeat(64) }), h.env, h.ctx);
  assert.equal(res2.status, 401);
});

test("a signed body that is not json gets 400 and a signed non-object gets 400", async () => {
  const h = new Harness();
  assert.equal((await h.app.fetch(h.signedRequest("not json"), h.env, h.ctx)).status, 400);
  assert.equal((await h.app.fetch(h.signedRequest("[1,2]"), h.env, h.ctx)).status, 400);
  assert.equal((await h.app.fetch(h.signedRequest("null"), h.env, h.ctx)).status, 400);
});

test("routes: only POST /interactions and GET /healthz exist", async () => {
  const h = new Harness();
  const get = await h.app.fetch(new Request("https://worker.example/interactions"), h.env, h.ctx);
  assert.equal(get.status, 404);
  const other = await h.app.fetch(h.signedRequest(PING, { path: "other" }), h.env, h.ctx);
  assert.equal(other.status, 404);
  const health = await h.app.fetch(new Request("https://worker.example/healthz"), h.env, h.ctx);
  assert.equal(health.status, 200);
  assert.equal(await health.text(), "ok");
  const postHealth = await h.app.fetch(
    new Request("https://worker.example/healthz", { method: "POST" }),
    h.env,
    h.ctx,
  );
  assert.equal(postHealth.status, 404);
});

test("a missing or malformed key and a wrong project both fail closed", async () => {
  for (const env of [
    makeEnv({ DISCORD_PUBLIC_KEY: "" }),
    makeEnv({ DISCORD_PUBLIC_KEY: "abc" }),
    makeEnv({ DISCORD_PUBLIC_KEY: "zz".repeat(32) }),
    makeEnv({ PROJECT: `${content.project.slug}-other` }),
    makeEnv({ PROJECT: "" }),
  ]) {
    const h = new Harness(env);
    const res = await h.app.fetch(h.signedRequest(PING), env, h.ctx);
    assert.equal(res.status, 500);
  }
  assert.equal(PUBLIC_KEY.length, 64);
});

test("an unsupported interaction type is answered privately and not acted on", async () => {
  const h = new Harness();
  const res = await h.send({ type: 4, data: {} });
  assert.equal(res.status, 200);
  assert.equal(res.body.data.flags & 64, 64);
});

test("a flood of unsigned requests makes no outbound call and reads nothing", async () => {
  const h = new Harness();
  h.router = () => new Response("unexpected", { status: 500 });
  const body = JSON.stringify({ type: 2, data: { name: "release" } });
  for (let n = 0; n < 50; n++) {
    const res = await h.app.fetch(h.signedRequest(body, { signature: "00".repeat(64) }), h.env, h.ctx);
    assert.equal(res.status, 401);
  }
  assert.equal(h.calls.length, 0);
});
