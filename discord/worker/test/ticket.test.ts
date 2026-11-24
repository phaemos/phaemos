import assert from "node:assert/strict";
import { test } from "node:test";
import { buildTicketBody, parseTagIds, parseTicketModalId, readTicketForm } from "../src/ticket.ts";
import { ALICE, BOB, CHANNEL, GUILD, Harness, content, id, json, makeEnv, shape, str } from "./helpers.ts";

// a forum webhook address and a tag id, both made at run time so that no file holds one
const TICKETS = ["https://discord.com", "api", "webhooks", "2", "tickets-test-only"].join("/");
const TAG = id(70);
const kind = content.ticket_kinds[0]?.key ?? "";
const kindTitle = content.ticket_kinds[0]?.title ?? "";

const hook = (h: Harness) => h.calls.filter((c) => c.url.startsWith(TICKETS));
const env = (extra = {}) => makeEnv({ TICKETS_WEBHOOK_URL: TICKETS, ...extra });

function form(subject: string, details: string, kindKey = kind, user = ALICE, interaction?: string) {
  return {
    ...(interaction ? { id: interaction } : {}),
    type: 5,
    application_id: id(3),
    token: "t".repeat(40),
    guild_id: GUILD,
    channel_id: CHANNEL,
    member: { permissions: "311452355648", roles: [], user: { id: user } },
    data: {
      custom_id: `t|${kindKey}`,
      components: [
        { type: 18, component: { type: 4, custom_id: "subject", value: subject } },
        { type: 18, component: { type: 4, custom_id: "details", value: details } },
      ],
    },
  };
}

test("ticket: the command opens a form for a kind from the server's list", async () => {
  const h = new Harness(env());
  const res = await h.send({
    type: 2,
    application_id: id(3),
    token: "t".repeat(40),
    guild_id: GUILD,
    channel_id: CHANNEL,
    member: { permissions: "0", roles: [], user: { id: ALICE } },
    data: { id: id(99), name: "ticket", type: 1, options: [str("kind", kind)] },
  });
  assert.equal(res.body.type, 9);
  assert.equal(res.body.data.custom_id, `t|${kind}`);
  const inputs = res.body.data.components.map((c: any) => c.component);
  assert.deepEqual(
    inputs.map((c: any) => [c.custom_id, c.required, c.max_length]),
    [
      ["subject", true, 90],
      ["details", true, 1000],
    ],
  );
  assert.equal(h.calls.length, 0);
});

test("ticket: a kind that is not in the list opens no form", async () => {
  const h = new Harness(env());
  const res = await h.send({
    type: 2,
    guild_id: GUILD,
    channel_id: CHANNEL,
    member: { permissions: "0", roles: [], user: { id: ALICE } },
    data: { id: id(99), name: "ticket", type: 1, options: [str("kind", "nonsense")] },
  });
  assert.equal(res.body.type, 4);
  assert.equal(shape(res).ephemeral, true);
});

test("ticket: a form becomes one forum post with the kind in its name and the kind's tag", async () => {
  const h = new Harness(env({ TICKET_TAG_IDS: `${kind}:${TAG}` }));
  h.router = () => json({ id: "1" });
  const res = await h.send(form("Cannot sign in", "I get an error after the code"));
  assert.equal(res.body.type, 4);
  const [call] = hook(h);
  assert.equal(call?.method, "POST");
  const body = JSON.parse(call?.body ?? "{}");
  assert.equal(body.thread_name, `${kindTitle}: Cannot sign in`);
  assert.deepEqual(body.applied_tags, [TAG]);
  assert.deepEqual(body.allowed_mentions, { parse: [] });
  const fields = body.embeds[0].fields.map((f: any) => [f.name, f.value]);
  assert.deepEqual(fields[0], ["From", `<@${ALICE}>`]);
  assert.deepEqual(fields[2], ["Status", "Open"]);
  assert.ok(!("content" in body), "no loose text outside the embed");
});

test("ticket: the member is told privately what happens next and the details are never echoed", async () => {
  const h = new Harness(env());
  h.router = () => json({});
  const res = await h.send(form("Private subject", "a very private detail"));
  assert.equal(shape(res).ephemeral, true);
  const text = shape(res).content;
  assert.ok(text.includes("within two days"));
  assert.ok(!text.includes("Private subject") && !text.includes("very private detail"));
  assert.ok(!JSON.stringify(res.body).includes("private detail"));
});

test("ticket: without the tag secret the post still goes, the kind being in its name", async () => {
  const h = new Harness(env());
  h.router = () => json({});
  await h.send(form("Subject", "Details"));
  const body = JSON.parse(hook(h)[0]?.body ?? "{}");
  assert.equal(body.applied_tags, undefined);
  assert.ok(body.thread_name.startsWith(kindTitle));
});

test("ticket: mentions in the words are neutralised and the post can ping nobody", async () => {
  const h = new Harness(env());
  h.router = () => json({});
  await h.send(form("@everyone <@&123> look", `ping <@${id(80)}> and @here <#123>`));
  const body = JSON.parse(hook(h)[0]?.body ?? "{}");
  assert.deepEqual(body.allowed_mentions, { parse: [] });
  const text = JSON.stringify(body.embeds[0].fields.slice(3));
  assert.ok(!/(?<!\\)<[@#]/.test(text), "mention markup is escaped with a backslash");
});

test("ticket: an empty or over long form is refused and nothing is posted", async () => {
  const h = new Harness(env());
  h.router = () => json({});
  for (const [s, d] of [
    ["", "details"],
    ["   ", "details"],
    ["subject", ""],
    ["subject", " \n "],
    ["s".repeat(91), "details"],
    ["subject", "d".repeat(1001)],
  ] as const) {
    const res = await h.send(form(s, d));
    assert.equal(shape(res).ephemeral, true);
    assert.ok(shape(res).content.startsWith("Please give a subject"));
  }
  assert.equal(h.calls.length, 0);
});

test("ticket: one ticket in ten minutes for each member", async () => {
  const h = new Harness(env());
  h.router = () => json({});
  assert.ok(shape(await h.send(form("One", "Details"))).content.startsWith("Thank you"));
  assert.ok(shape(await h.send(form("Two", "Details"))).content.startsWith("Please wait ten minutes"));
  assert.ok(shape(await h.send(form("Other member", "Details", kind, BOB))).content.startsWith("Thank you"));
  h.clock += 10 * 60 * 1000 + 1;
  assert.ok(shape(await h.send(form("Three", "Details"))).content.startsWith("Thank you"));
  assert.equal(hook(h).length, 3);
});

test("ticket: when Discord certainly refuses the post the member is told to email and may try again", async () => {
  const h = new Harness(env());
  let fail = true;
  h.router = () => (fail ? new Response("no", { status: 400 }) : json({}));
  const res = await h.send(form("Subject", "Details"));
  assert.equal(shape(res).ephemeral, true);
  assert.ok(shape(res).content.includes(content.project.contact_email));
  assert.ok(
    shape(res).content.includes(`<${content.project.contact_page}>`),
    "the address is followed by a page that links",
  );
  fail = false;
  assert.ok(shape(await h.send(form("Subject", "Details"))).content.startsWith("Thank you"));
});

test("ticket: after a timeout or a server error the cooldown stays, since the post may have been made", async () => {
  for (const status of [500, 502]) {
    const h = new Harness(env());
    h.router = () => new Response("no", { status });
    const first = shape(await h.send(form("Subject", "Details")));
    assert.ok(first.content.includes("could not tell whether"));
    assert.ok(first.content.includes(content.project.contact_email));
    h.router = () => json({});
    assert.ok(shape(await h.send(form("Subject", "Details"))).content.startsWith("Please wait ten minutes"));
    assert.equal(hook(h).length, 1);
  }
  const slow = new Harness(env());
  slow.router = () => new Promise<Response>(() => {});
  assert.ok(shape(await slow.send(form("Subject", "Details"))).content.includes("could not tell whether"));
  slow.router = () => json({});
  assert.ok(shape(await slow.send(form("Subject", "Details"))).content.startsWith("Please wait ten minutes"));
});

test("ticket: the same interaction delivered twice makes one post", async () => {
  const h = new Harness(env());
  h.router = () => json({});
  const same = id(91);
  const a = shape(await h.send(form("Subject", "Details", kind, ALICE, same)));
  const b = shape(await h.send(form("Subject", "Details", kind, ALICE, same)));
  assert.ok(a.content.startsWith("Thank you") && b.content.startsWith("Thank you"));
  assert.equal(hook(h).length, 1);
  h.clock += 5 * 60 * 1000 + 1;
  h.clock += 10 * 60 * 1000;
  assert.ok(
    shape(await h.send(form("Subject", "Details", kind, ALICE, same))).content.startsWith("Thank you"),
  );
  assert.equal(hook(h).length, 2);
});

test("ticket: a missing or wrong webhook secret fails the same way and posts nowhere", async () => {
  for (const address of [
    undefined,
    ["https://example.org", "api", "webhooks", "1", "x"].join("/"),
    "not an address",
  ]) {
    const h = new Harness(makeEnv({ TICKETS_WEBHOOK_URL: address }));
    const res = await h.send(form("Subject", "Details"));
    assert.ok(shape(res).content.includes(content.project.contact_email));
    assert.equal(h.calls.length, 0);
  }
});

test("ticket: the reports webhook is never used for a ticket", async () => {
  const h = new Harness(env());
  h.router = () => json({});
  await h.send(form("Subject", "Details"));
  assert.ok(h.calls.every((c) => c.url.startsWith(TICKETS)));
});

test("ticket: a forged or replayed form is refused by the signature check", async () => {
  const h = new Harness(env());
  h.router = () => json({});
  const body = JSON.stringify(form("Subject", "Details"));
  const forged = await h.app.fetch(h.signedRequest(body, { signature: "0".repeat(128) }), h.env, h.ctx);
  assert.equal(forged.status, 401);
  const stamp = String(Math.floor(h.clock / 1000) - 3600);
  const replayed = await h.app.fetch(h.signedRequest(body, { timestamp: stamp }), h.env, h.ctx);
  assert.equal(replayed.status, 401);
  const other = JSON.stringify(form("Changed after signing", "Details"));
  const signature = (await import("./helpers.ts")).signBody(String(Math.floor(h.clock / 1000)), body);
  const tampered = await h.app.fetch(h.signedRequest(other, { signature }), h.env, h.ctx);
  assert.equal(tampered.status, 401);
  assert.equal(h.calls.length, 0);
});

test("ticket: a form id that names no kind, or no member, is refused", async () => {
  const h = new Harness(env());
  h.router = () => json({});
  assert.equal(parseTicketModalId("t|nonsense", content.ticket_kinds), null);
  assert.equal(parseTicketModalId("r|123", content.ticket_kinds), null);
  assert.equal(parseTicketModalId(`t|${kind}|extra`, content.ticket_kinds), null);
  const res = await h.send(form("Subject", "Details", "nonsense"));
  assert.equal(shape(res).ephemeral, true);
  assert.equal(h.calls.length, 0);
});

test("ticket: helpers read the form and the tag secret strictly", () => {
  assert.deepEqual(
    readTicketForm([
      { component: { custom_id: "subject", value: " a  b " } },
      { custom_id: "details", value: " d " },
    ]),
    {
      subject: "a b",
      details: "d",
    },
  );
  assert.equal(readTicketForm([]), null);
  const tags = parseTagIds(`a:${TAG}, b:notanid,${kind}:${id(71)}`);
  assert.equal(tags.get("a"), TAG);
  assert.equal(tags.has("b"), false);
  assert.equal(tags.get(kind), id(71));
  const body = buildTicketBody(
    { member: ALICE, kind: { key: "x", title: "X" }, subject: "s", details: "d" },
    tags,
  );
  assert.equal(body.applied_tags, undefined);
});
