import assert from "node:assert/strict";
import { test } from "node:test";
import { REPORT_COOLDOWN_MS, buildModalId, modalValue, parseModalId, webhookTarget } from "../src/report.ts";
import {
  ALICE,
  BOB,
  CHANNEL,
  GUILD,
  Harness,
  MESSAGE,
  WEBHOOK,
  command,
  content,
  golden,
  id,
  json,
  makeEnv,
  shape,
  str,
  user,
} from "./helpers.ts";

const hook = (h: Harness) => h.calls.filter((c) => c.url.startsWith(WEBHOOK.split("?")[0] ?? ""));

test("report: a slash report reaches the staff webhook with exactly the documented fields", async () => {
  const h = new Harness();
  h.router = () => json({ id: "1" });
  const res = await h.send(
    command("report", [str("details", "Someone is posting my address"), user("member", BOB)]),
  );
  assert.equal(res.body.type, 4);
  assert.equal(shape(res).ephemeral, true);
  const [call] = hook(h);
  assert.equal(call?.method, "POST");
  assert.equal(new URL(call?.url ?? "").searchParams.get("wait"), "true");
  const payload = JSON.parse(call?.body ?? "{}");
  assert.deepEqual(payload.allowed_mentions, { parse: [] });
  assert.deepEqual(Object.keys(payload).sort(), ["allowed_mentions", "embeds"]);
  const embed = payload.embeds[0];
  assert.equal(embed.title, "Report from a member");
  assert.deepEqual(Object.keys(embed).sort(), ["fields", "title"]);
  assert.deepEqual(
    embed.fields.map((f: { name: string; value: string }) => [f.name, f.value]),
    [
      ["Reported by", `<@${ALICE}>`],
      ["About", `<@${BOB}>`],
      ["Where", `<#${CHANNEL}>`],
      ["Why, in the reporter's words, not verified", "Someone is posting my address"],
    ],
  );
  assert.ok(!(call?.body ?? "").includes("username"), "no display name or tag is sent");
});

test("report: no member named is said in words", async () => {
  const h = new Harness();
  h.router = () => json({});
  await h.send(command("report", [str("details", "Spam in general")]));
  const embed = JSON.parse(hook(h)[0]?.body ?? "{}").embeds[0];
  assert.equal(embed.fields[1].value, "No member named");
});

test("report: the reporter's markup and mentions are neutralised for staff too", async () => {
  const h = new Harness();
  h.router = () => json({});
  await h.send(command("report", [str("details", "[click](http://evil.example) <@&1> @everyone **x**")]));
  const why = JSON.parse(hook(h)[0]?.body ?? "{}").embeds[0].fields.at(-1).value as string;
  assert.ok(why.includes("\\[click\\]\\(http://evil.example\\)"));
  assert.ok(why.includes("\\<@&1\\>"));
});

test("report: empty, blank and too long details are refused without a call", async () => {
  const h = new Harness();
  for (const details of ["", "   \n ", "x".repeat(1001)]) {
    const res = await h.send(command("report", [str("details", details)]));
    assert.equal(shape(res).ephemeral, true);
    assert.ok(res.body.data.content.startsWith("Please describe the problem"));
  }
  assert.equal(h.calls.length, 0);
  const ok = new Harness();
  ok.router = () => json({});
  await ok.send(command("report", [str("details", "x".repeat(1000))]));
  assert.equal(hook(ok).length, 1);
});

test("report: a webhook failure tells the member where to write and lets them try again", async () => {
  const h = new Harness();
  h.router = () => json({}, 500);
  const res = await h.send(command("report", [str("details", "problem")]));
  golden("report.failed", shape(res));
  assert.ok(res.body.data.content.includes(content.project.contact_email));
  h.router = () => json({});
  const retry = await h.send(command("report", [str("details", "problem")]));
  assert.ok(retry.body.data.content.startsWith("Thank you."));
});

test("report: a network failure and a missing webhook give the same plain answer", async () => {
  const h = new Harness();
  h.router = () => Promise.reject(new Error("down"));
  const res = await h.send(command("report", [str("details", "problem")]));
  assert.ok(res.body.data.content.startsWith("We could not record your report."));
  for (const value of [
    undefined,
    "",
    "not a url",
    ["http://discord.com", "api", "webhooks", "1", "x"].join("/"),
    ["https://evil.example", "api", "webhooks", "1", "x"].join("/"),
  ]) {
    const g = new Harness(makeEnv({ REPORTS_WEBHOOK_URL: value }));
    const r = await g.send(command("report", [str("details", "problem")]));
    assert.ok(r.body.data.content.startsWith("We could not record your report."), String(value));
    assert.equal(g.calls.length, 0);
  }
});

test("report: one a minute for each member and the limit is per member", async () => {
  const h = new Harness();
  h.router = () => json({});
  await h.send(command("report", [str("details", "one")]));
  const second = await h.send(command("report", [str("details", "two")]));
  golden("report.wait", shape(second));
  assert.equal(hook(h).length, 1);
  const other = await h.send(command("report", [str("details", "three")], { user: BOB }));
  assert.ok(other.body.data.content.startsWith("Thank you."));
  h.clock += REPORT_COOLDOWN_MS + 1;
  const later = await h.send(command("report", [str("details", "four")]));
  assert.ok(later.body.data.content.startsWith("Thank you."));
});

test("report: the webhook address must be a Discord webhook over https", () => {
  assert.ok(webhookTarget(WEBHOOK));
  assert.equal(webhookTarget(`${WEBHOOK}?evil=1`)?.searchParams.get("evil"), null);
  assert.equal(webhookTarget("https://discord.com/other/path"), null);
  assert.equal(webhookTarget(undefined), null);
});

function messageCommand(authorId: string | null, text: string) {
  return command("Report to moderators", [], {
    type: 3,
    extra: {
      target_id: MESSAGE,
      resolved: {
        messages: { [MESSAGE]: { content: text, ...(authorId ? { author: { id: authorId } } : {}) } },
      },
    },
  });
}

function submit(customId: string, why: string, user = ALICE) {
  return {
    type: 5,
    application_id: id(3),
    token: "t".repeat(40),
    guild_id: GUILD,
    channel_id: CHANNEL,
    member: { permissions: "0", user: { id: user } },
    data: {
      custom_id: customId,
      components: [{ type: 18, id: 1, component: { type: 4, id: 2, custom_id: "why", value: why } }],
    },
  };
}

test("message command: opens a small form with one optional field", async () => {
  const h = new Harness();
  const res = await h.send(messageCommand(BOB, "a rude message"));
  assert.equal(res.body.type, 9);
  assert.equal(res.body.data.title, "Report to moderators");
  assert.ok(res.body.data.title.length <= 45);
  assert.ok(res.body.data.custom_id.length <= 100);
  const label = res.body.data.components[0];
  assert.equal(label.type, 18);
  assert.equal(label.component.required, false);
  assert.equal(label.component.max_length, 500);
  assert.ok(label.label.length <= 45);
  assert.equal(h.calls.length, 0, "nothing is sent until the form is submitted");
});

test("message command: the form id carries only the message id", async () => {
  assert.equal(buildModalId(MESSAGE), `r|${MESSAGE}`);
  assert.deepEqual(parseModalId(`r|${MESSAGE}`), { messageId: MESSAGE });
  const h = new Harness();
  const res = await h.send(messageCommand(BOB, "words that must never travel in the id"));
  assert.equal(res.body.data.custom_id, `r|${MESSAGE}`);
});

test("message command: the form says who will see the report and where to send one about staff", async () => {
  const h = new Harness();
  const res = await h.send(messageCommand(BOB, "x"));
  const description: string = res.body.data.components[0].component
    ? res.body.data.components[0].description
    : "";
  assert.ok(description.length <= 100);
  assert.ok(description.includes("Every moderator sees this and your name"));
  assert.ok(description.includes(content.project.contact_email));
});

test("report: the thank you says who can see it and where to write about staff", async () => {
  const h = new Harness();
  h.router = () => json({});
  const res = await h.send(command("report", [str("details", "problem")]));
  golden("report.thanks", shape(res));
  assert.ok(res.body.data.content.includes("Every moderator can see your report and your name"));
  assert.ok(
    res.body.data.content.includes(
      `write to ${content.project.contact_email} or see <${content.project.contact_page}>`,
    ),
  );
});

test("message command: the entry carries the link and the reporter's words and no quoted message", async () => {
  const h = new Harness();
  h.router = () => json({});
  const open = await h.send(messageCommand(BOB, "you are all idiots [x](http://evil.example)"));
  const res = await h.send(submit(open.body.data.custom_id, "Insults in general"));
  golden("report.form.thanks", shape(res));
  const body = hook(h)[0]?.body ?? "";
  assert.ok(!body.includes("idiots"), "the reported message is never copied");
  const embed = JSON.parse(body).embeds[0];
  const fields = Object.fromEntries(
    embed.fields.map((f: { name: string; value: string }) => [f.name, f.value]),
  );
  assert.equal(fields["Reported by"], `<@${ALICE}>`);
  assert.ok(
    !Object.values(fields).some((v) => String(v).includes(BOB)),
    "the author is not taken from the form",
  );
  assert.ok(String(fields.Where).startsWith(`<https://discord.com/channels/${GUILD}/${CHANNEL}/${MESSAGE}>`));
  assert.ok(String(fields.Where).includes("The link is the evidence"));
  assert.equal(fields["Why, in the reporter's words, not verified"], "Insults in general");
  assert.deepEqual(Object.keys(fields).sort(), [
    "About",
    "Reported by",
    "Where",
    "Why, in the reporter's words, not verified",
  ]);
});

test("message command: a changed form id cannot put words or a member in the entry", async () => {
  const h = new Harness();
  h.router = () => json({});
  await h.send(submit(`r|${MESSAGE}|${BOB}|made up words`, "text"));
  await h.send(submit(`r|${MESSAGE}x`, "text"));
  assert.equal(hook(h).length, 0);
  const ok = await h.send(submit(`r|${id(77)}`, "text"));
  assert.ok(ok.body.data.content.startsWith("Thank you."));
  const sent = hook(h)[0]?.body ?? "";
  assert.ok(sent.includes(`/${CHANNEL}/${id(77)}`), "the channel is the one in the signed interaction");
});

test("message command: an empty reason is still sent and says so", async () => {
  const h = new Harness();
  h.router = () => json({});
  const open = await h.send(messageCommand(null, "x"));
  await h.send(submit(open.body.data.custom_id, ""));
  const embed = JSON.parse(hook(h)[0]?.body ?? "{}").embeds[0];
  const fields = Object.fromEntries(
    embed.fields.map((f: { name: string; value: string }) => [f.name, f.value]),
  );
  assert.equal(fields["Why, in the reporter's words, not verified"], "No words were added");
});

test("message command: a forged form id or a missing target is refused", async () => {
  const h = new Harness();
  for (const bad of ["", "x|1|2", "r|abc", "r|../../x", "report", `r|${MESSAGE}|`]) {
    const res = await h.send(submit(bad, "text"));
    assert.equal(shape(res).ephemeral, true, bad);
  }
  assert.equal(h.calls.length, 0);
  const noTarget = await h.send(
    command("Report to moderators", [], { type: 3, extra: { target_id: "nope" } }),
  );
  assert.equal(shape(noTarget).ephemeral, true);
});

test("message command: a form submitted twice in a minute is limited", async () => {
  const h = new Harness();
  h.router = () => json({});
  const open = await h.send(messageCommand(BOB, "x"));
  await h.send(submit(open.body.data.custom_id, "a"));
  const again = await h.send(submit(open.body.data.custom_id, "b"));
  assert.equal(again.body.data.content, "Please wait a minute before sending another report.");
});

test("modal values are found in a label or an old style row", () => {
  assert.equal(modalValue([{ type: 1, components: [{ custom_id: "why", value: "a" }] }], "why"), "a");
  assert.equal(modalValue([{ type: 18, component: { custom_id: "why", value: "b" } }], "why"), "b");
  assert.equal(modalValue([{ custom_id: "other", value: "c" }], "why"), undefined);
  assert.equal(modalValue("nope", "why"), undefined);
});
