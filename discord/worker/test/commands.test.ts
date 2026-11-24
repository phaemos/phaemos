import assert from "node:assert/strict";
import { test } from "node:test";
import { Harness, STAFF, bool, command, content, golden, id, shape, str } from "./helpers.ts";

async function ask(h: Harness, name: string, options = [] as ReturnType<typeof str>[], perms?: string) {
  return h.send(command(name, options, perms ? { permissions: perms } : {}));
}

test("every command in the content has a handler that answers", async () => {
  const h = new Harness();
  for (const c of content.commands) {
    if (c.type === "message" || c.name === "mod") continue;
    const options: ReturnType<typeof str>[] = [];
    const res = await ask(h, c.name, options);
    assert.equal(res.status, 200, c.name);
    assert.ok([4, 5].includes(res.body.type), `${c.name} answered with type ${res.body.type}`);
  }
});

test("help lists the commands for a member and adds the staff command for staff", async () => {
  const h = new Harness();
  const member = await ask(h, "help");
  golden("help.member", shape(member));
  assert.ok(!member.body.data.content.includes("/mod"));
  assert.ok(member.body.data.content.endsWith(`You can try them in #${content.project.commands_channel}.`));
  const staff = await ask(h, "help", [], STAFF);
  golden("help.staff", shape(staff));
  assert.ok(staff.body.data.content.includes("/mod"));
  assert.equal(shape(member).ephemeral, true);
});

for (const list of ["docs", "faq", "hardware"] as const) {
  test(`${list}: every topic answers with its text and links`, async () => {
    const h = new Harness();
    for (const topic of content[list]) {
      const res = await ask(h, list, [str(list === "hardware" ? "part" : "topic", topic.key)]);
      golden(`${list}.${topic.key}`, shape(res));
      assert.equal(shape(res).ephemeral, false, "visible to everyone by default");
      for (const link of topic.links) assert.ok(res.body.data.content.includes(`<${link.url}>`));
    }
  });

  test(`${list}: an unknown topic is refused privately and nothing is echoed`, async () => {
    const h = new Harness();
    const name = list === "hardware" ? "part" : "topic";
    const res = await ask(h, list, [str(name, "<@everyone> [x](http://bad.example)")]);
    assert.equal(shape(res).ephemeral, true);
    assert.ok(!res.body.data.content.includes("bad.example"));
    golden(`${list}.unknown`, shape(res));
  });
}

test("the share switch changes who sees an answer in both directions", async () => {
  const h = new Harness();
  const first = content.docs[0]?.key ?? "";
  const priv = await h.send(command("docs", [str("topic", first), bool("share", false)]));
  assert.equal(shape(priv).ephemeral, true);
  const sub = (opts: unknown[]) => [{ name: "new", type: 1, options: [...opts] }];
  const pub = await h.send(command("issue", sub([bool("share", true)]) as never));
  assert.equal(shape(pub).ephemeral, false);
  const def = await h.send(command("issue", sub([]) as never));
  assert.equal(shape(def).ephemeral, true);
});

test("issue new: answers privately by default with the fixed text", async () => {
  const h = new Harness();
  const res = await h.send(command("issue", [{ name: "new", type: 1, options: [] }] as never));
  assert.equal(shape(res).ephemeral, true);
  golden("static.bug", shape(res));
});

for (const name of ["security", "contribute", "roles"]) {
  test(`${name}: answers privately by default with the fixed text`, async () => {
    const h = new Harness();
    const res = await ask(h, name);
    assert.equal(shape(res).ephemeral, true);
    golden(`static.${name}`, shape(res));
  });
}

test("security answer sends reports away from the server", async () => {
  const h = new Harness();
  const res = await ask(h, "security");
  const text: string = res.body.data.content;
  assert.ok(text.includes(content.project.security_form));
  assert.ok(text.includes(content.project.security_email));
  assert.ok(/never in this server/i.test(text));
});

test("mod guide: a moderator reads every guide, privately", async () => {
  const h = new Harness();
  for (const g of content.mod_guide) {
    const res = await h.send(
      command("mod", [{ name: "guide", type: 1, options: [str("topic", g.key)] } as never], {
        permissions: STAFF,
      }),
    );
    assert.equal(shape(res).ephemeral, true);
    golden(`mod.guide.${g.key}`, shape(res));
  }
});

test("mod reply: a moderator posts every template to the channel", async () => {
  const h = new Harness();
  for (const r of content.mod_reply) {
    const res = await h.send(
      command("mod", [{ name: "reply", type: 1, options: [str("template", r.key)] } as never], {
        permissions: STAFF,
      }),
    );
    assert.equal(shape(res).ephemeral, false);
    assert.ok(res.body.data.content.startsWith("From the moderators: "));
    golden(`mod.reply.${r.key}`, shape(res));
  }
});

test("mod: a member is refused even if registration let them reach it", async () => {
  const h = new Harness();
  const sub = { name: "reply", type: 1, options: [str("template", "security")] } as never;
  for (const perms of ["311452355648", "0", "8191", "8", "", "not a number", "2252899459538944x"]) {
    const res = await h.send(command("mod", [sub], { permissions: perms }));
    assert.equal(shape(res).ephemeral, true, perms);
    assert.equal(res.body.data.content, "That command is for the moderators.", perms);
  }
  const noPerms = command("mod", [sub]);
  (noPerms.member as Record<string, unknown>).permissions = undefined;
  assert.equal((await h.send(noPerms)).body.data.content, "That command is for the moderators.");
  const exact = await h.send(command("mod", [sub], { permissions: "8192" }));
  assert.ok(exact.body.data.content.startsWith("From the moderators"));
  const reply = await h.send(
    command("mod", [{ name: "guide", type: 1, options: [str("topic", "raid")] } as never], {
      permissions: "8192",
    }),
  );
  assert.ok(reply.body.data.content.length > 0);
});

test("mod: an unknown template or guide is refused", async () => {
  const h = new Harness();
  const res = await h.send(
    command("mod", [{ name: "reply", type: 1, options: [str("template", "nope")] } as never], {
      permissions: STAFF,
    }),
  );
  assert.equal(res.body.data.content, "We do not know that command. Type /help.");
  const none = await h.send(command("mod", [], { permissions: STAFF }));
  assert.equal(shape(none).ephemeral, true);
});

test("an unknown command is answered privately", async () => {
  const h = new Harness();
  const res = await ask(h, "nothing");
  assert.equal(res.body.data.content, "We do not know that command. Type /help.");
  assert.equal(shape(res).ephemeral, true);
  const noName = await h.send({ type: 2, guild_id: "x", data: {} });
  assert.equal(shape(noName).ephemeral, true);
});

test("a command used outside the server is refused", async () => {
  const h = new Harness();
  const res = await h.send(command("help", [], { guild: false }));
  assert.equal(res.body.data.content, "These commands work inside the server only.");
});

test("a message command is not reachable as a slash command and the reverse", async () => {
  const h = new Harness();
  const asSlash = await h.send(command("Report to moderators"));
  assert.equal(asSlash.body.data.content, "We do not know that command. Type /help.");
  const asMessage = await h.send(command("help", [], { type: 3, extra: { target_id: "9".repeat(18) } }));
  assert.equal(asMessage.body.data.content, "We do not know that command. Type /help.");
});

test("roles points at Channels and Roles", async () => {
  const h = new Harness();
  const res = await ask(h, "roles");
  assert.ok(res.body.data.content.includes("<id:customize>"));
});

test("issue number option is only ever a bounded integer", async () => {
  const h = new Harness();
  for (const bad of [0, -1, 1.5, 100000000, Number.MAX_SAFE_INTEGER, "12", "../../etc", null]) {
    const res = await h.send(
      command("issue", [
        { name: "show", type: 1, options: [{ name: "number", type: 4, value: bad }] },
      ] as never),
    );
    assert.equal(shape(res).ephemeral, true, String(bad));
  }
  assert.equal(h.calls.length, 0, "no call left the worker");
});

// staff are known by role when the secret lists the role ids. the ids here are made up for the test.
const MOD_ROLE = id(50);
const MAINT_ROLE = id(51);
const reply = { name: "reply", type: 1, options: [str("template", "security")] } as never;

test("staff by role: a moderator is let in with no permission bits, as in the log channel", async () => {
  const h = new Harness();
  h.env = { ...h.env, STAFF_ROLE_IDS: `${MOD_ROLE},${MAINT_ROLE}` };
  for (const role of [MOD_ROLE, MAINT_ROLE]) {
    const res = await h.send(command("mod", [reply], { permissions: "0", roles: [id(60), role] }));
    assert.ok(res.body.data.content.startsWith("From the moderators"), role);
  }
});

test("staff by role: Manage Messages alone is not enough once roles are set", async () => {
  const h = new Harness();
  h.env = { ...h.env, STAFF_ROLE_IDS: MOD_ROLE };
  for (const roles of [[], [id(60)], [MAINT_ROLE]]) {
    const res = await h.send(command("mod", [reply], { permissions: STAFF, roles }));
    assert.equal(res.body.data.content, "That command is for the moderators.");
  }
});

test("staff by role: a secret with no valid id lets nobody in while a missing one falls back to the bit", async () => {
  const h = new Harness();
  h.env = { ...h.env, STAFF_ROLE_IDS: "not-an-id, 123" };
  const denied = await h.send(command("mod", [reply], { permissions: STAFF, roles: [MOD_ROLE] }));
  assert.equal(denied.body.data.content, "That command is for the moderators.");
  h.env = { ...h.env, STAFF_ROLE_IDS: undefined };
  const bit = await h.send(command("mod", [reply], { permissions: STAFF }));
  assert.ok(bit.body.data.content.startsWith("From the moderators"));
  const help = await h.send(command("help", [], { permissions: "0", roles: [MOD_ROLE] }));
  assert.ok(!help.body.data.content.includes("/mod"));
  h.env = { ...h.env, STAFF_ROLE_IDS: MOD_ROLE };
  const helpStaff = await h.send(command("help", [], { permissions: "0", roles: [MOD_ROLE] }));
  assert.ok(helpStaff.body.data.content.includes("/mod"));
});
