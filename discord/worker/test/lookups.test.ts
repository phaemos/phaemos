import assert from "node:assert/strict";
import { mock, test } from "node:test";
import { Harness, bool, command, content, golden, int, json, shape } from "./helpers.ts";

const repo = content.project.repository;

// a project without a hosted service has no status command, so these tests add one.
const statusContent: typeof content = {
  ...content,
  status: content.status ?? { url: "https://status-api.example/status", page: "https://status.example" },
  commands: content.commands.some((c) => c.name === "status")
    ? content.commands
    : [...content.commands, { name: "status", type: "chat_input", visibility: "public", share: true }],
};
const statusHarness = () => new Harness(undefined, statusContent);

function releaseBody(extra: Record<string, unknown> = {}) {
  return {
    tag_name: "v2.6.0",
    published_at: "2026-11-30T10:00:00Z",
    body: "### Added\n- Maintenance windows can repeat every week.\n\n### Fixed\n- Edge gateway keeps readings on reconnect.\n<!-- hidden -->\n![chart](http://x.example/a.png)\n[link text](http://evil.example)",
    ...extra,
  };
}

// a lookup answers in the same request, so the answer is public or private from the start.
async function ask(h: Harness, name: string, options: never[] | Record<string, unknown>[] = []) {
  // an issue lookup is now the show subcommand of /issue
  const wrapped = name === "issue" ? [{ name: "show", type: 1, options }] : options;
  const res = await h.send(command(name, wrapped as never));
  assert.equal(res.status, 200);
  assert.equal(res.body.type, 4, "answered directly and never deferred");
  return { ...shape(res), body: res.body };
}

// the address is parsed, so a host such as api.github.com.example.org is not taken for GitHub
const hostOf = (url: string) => new URL(url).hostname;
const githubCalls = (h: Harness) =>
  h.calls.filter((c) => new URL(c.url).protocol === "https:" && hostOf(c.url) === "api.github.com");
// the request verifies a signature first, so the time-out is only set a few turns later. move the clock on
// every turn until the request has answered.
async function tickUntilDone<T>(pending: Promise<T>): Promise<T> {
  let done = false;
  pending.then(
    () => {
      done = true;
    },
    () => {
      done = true;
    },
  );
  for (let n = 0; n < 500 && !done; n++) {
    await new Promise<void>((resolve) => setImmediate(resolve));
    mock.timers.tick(2201);
  }
  return pending;
}
const hang = (h: Harness) => {
  h.router = () => new Promise<Response>(() => {});
};

test("release: answers in the same request with the notes and makes no follow-up call", async () => {
  const h = new Harness();
  h.router = () => json(releaseBody());
  const res = await ask(h, "release");
  assert.equal(res.ephemeral, false, "visible to everyone by default");
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0]?.url, `https://api.github.com/repos/${repo}/releases/latest`);
  assert.equal(h.calls[0]?.headers["user-agent"], "community-commands-worker");
  golden("release.ok", { content: res.content, ephemeral: false });
  assert.ok(!res.content.includes("evil.example"));
  assert.ok(!res.content.includes("x.example"));
  assert.ok(!res.content.includes("hidden"));
});

test("release: a second command inside ten minutes uses the cache and makes no call", async () => {
  const h = new Harness();
  h.router = () => json(releaseBody());
  await ask(h, "release");
  h.clock += 9 * 60 * 1000;
  await ask(h, "release");
  assert.equal(h.calls.length, 1);
  h.clock += 2 * 60 * 1000;
  await ask(h, "release");
  assert.equal(h.calls.length, 2, "the cache has expired");
});

test("release: share false makes the answer private", async () => {
  const h = new Harness();
  h.router = () => json(releaseBody());
  assert.equal((await ask(h, "release", [bool("share", false)] as never)).ephemeral, true);
});

test("release: notes are cut to 600 characters and markup is escaped", async () => {
  const h = new Harness();
  h.router = () => json(releaseBody({ body: `**bold** a < b @everyone ${"word ".repeat(400)}` }));
  const { content: text } = await ask(h, "release");
  assert.ok(text.includes("\\*\\*bold\\*\\*"));
  assert.ok(text.includes("a \\< b"));
  assert.ok(text.length < 900);
  assert.ok(text.includes("..."));
});

test("release: 404 says there is no release yet", async () => {
  const h = new Harness();
  h.router = () => json({ message: "Not Found" }, 404);
  golden("release.none", { content: (await ask(h, "release")).content, ephemeral: false });
});

for (const [label, router] of [
  ["403", () => json({}, 403)],
  ["429", () => json({}, 429)],
  ["500", () => json({}, 500)],
  ["network error", () => Promise.reject(new Error("down"))],
  ["not json", () => new Response("<html>", { status: 200 })],
  ["missing tag", () => json({ body: "x" })],
  ["too large", () => new Response("x".repeat(600 * 1024), { status: 200 })],
  ["redirect", () => new Response("", { status: 301, headers: { location: "https://evil.example" } })],
] as const) {
  test(`release: ${label} gives the plain fallback with the link`, async () => {
    const h = new Harness();
    h.router = router as never;
    const { content: text } = await ask(h, "release");
    assert.equal(
      text,
      `We could not reach GitHub just now. The releases are at <${content.project.releases}>`,
    );
    golden("release.down", { content: text, ephemeral: false });
  });
}

test("release: a stale answer is served when GitHub is down", async () => {
  const h = new Harness();
  h.router = () => json(releaseBody());
  await ask(h, "release");
  h.clock += 30 * 60 * 1000;
  h.router = () => json({}, 503);
  assert.ok((await ask(h, "release")).content.startsWith("Latest release: v2.6.0"));
});

test("release: a read that hangs is cut off inside Discord's three seconds", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const h = new Harness();
    hang(h);
    const pending = h.send(command("release"));
    // the request has to do its work before the timer is moved on.
    const res = await tickUntilDone(pending);
    assert.equal(res.body.type, 4);
    assert.ok(res.body.data.content.startsWith("We could not reach GitHub just now."));
  } finally {
    mock.timers.reset();
  }
});

test("release: identical commands that arrive together make one call", async () => {
  const h = new Harness();
  h.router = () => json(releaseBody());
  await Promise.all([ask(h, "release"), ask(h, "release"), ask(h, "release")]);
  assert.equal(githubCalls(h).length, 1);
});

test("release: the GitHub token is sent only to GitHub", async () => {
  const h = new Harness();
  h.env = { ...h.env, GITHUB_TOKEN: "test-token-value" };
  h.router = () => json(releaseBody());
  await ask(h, "release");
  assert.equal(h.calls[0]?.headers.authorization, "Bearer test-token-value");
  assert.equal(h.calls.length, 1);
});

const issueBody = (extra: Record<string, unknown> = {}) => ({
  number: 412,
  title: "Pico 2W drops its link",
  state: "open",
  labels: [{ name: "bug" }, { name: "firmware" }],
  ...extra,
});

test("issue: shows kind, state, title, labels and a link", async () => {
  const h = new Harness();
  h.router = () => json(issueBody());
  const res = await ask(h, "issue", [int("number", 412)] as never);
  assert.equal(h.calls[0]?.url, `https://api.github.com/repos/${repo}/issues/412`);
  golden("issue.open", { content: res.content, ephemeral: false });
});

test("issue: a merged pull request and a closed issue are told apart", async () => {
  const h = new Harness();
  h.router = (c) =>
    c.url.endsWith("/issues/7")
      ? json(issueBody({ state: "closed", pull_request: { merged_at: "2026-11-01T00:00:00Z" }, labels: [] }))
      : json(issueBody({ state: "closed" }));
  golden("issue.merged", {
    content: (await ask(h, "issue", [int("number", 7)] as never)).content,
    ephemeral: false,
  });
  golden("issue.closed", {
    content: (await ask(h, "issue", [int("number", 8)] as never)).content,
    ephemeral: false,
  });
});

test("issue: author text in the title and labels is neutralised", async () => {
  const h = new Harness();
  h.router = () =>
    json(
      issueBody({
        title: "[click](http://evil.example) @everyone <@12345> **loud** `code`\nsecond line \u202e",
        labels: [{ name: "_x_" }],
      }),
    );
  const { content: text } = await ask(h, "issue", [int("number", 5)] as never);
  golden("issue.hostile", { content: text, ephemeral: false });
  assert.ok(!text.includes("\u202e"));
  assert.ok(!/(^|[^\\])\[click\]/.test(text), "no live link syntax");
  assert.ok(!text.includes("\n\n"));
});

test("issue: a number that does not exist is answered privately at once and never publicly", async () => {
  const h = new Harness();
  h.router = () => json({ message: "Not Found" }, 404);
  const res = await ask(h, "issue", [int("number", 999)] as never);
  assert.equal(res.body.data.flags & 64, 64, "private from the first and only reply");
  golden("issue.missing", { content: res.content, ephemeral: true });
  assert.equal(h.calls.length, 1, "no delete and no follow-up");
  // even when the member asks to share, a missing number stays private.
  const shared = await ask(h, "issue", [int("number", 999), bool("share", true)] as never);
  assert.equal(shared.ephemeral, true);
  assert.equal(h.calls.length, 1, "the miss is cached");
});

test("issue: GitHub being down gives the plain link", async () => {
  const h = new Harness();
  h.router = () => json({}, 503);
  golden("issue.down", {
    content: (await ask(h, "issue", [int("number", 412)] as never)).content,
    ephemeral: false,
  });
});

test("issue: the number is the only thing placed in the address", async () => {
  const h = new Harness();
  h.router = () => json(issueBody());
  await ask(h, "issue", [int("number", 99999999)] as never);
  assert.match(h.calls[0]?.url ?? "", /^https:\/\/api\.github\.com\/repos\/[^/]+\/[^/]+\/issues\/\d{1,8}$/);
});

const statusBody = (extra: Record<string, unknown> = {}) => ({
  status: "operational",
  api: "ok",
  database: "ok",
  redis: "ok",
  model: "ok",
  version: "2.5.0",
  ...extra,
});

test("status: is answered when the content has a status address", async () => {
  const h = statusHarness();
  const status = statusContent.status;
  assert.ok(status);
  h.router = () => json(statusBody());
  h.clock = Date.UTC(2026, 10, 30, 14, 5);
  const res = await ask(h, "status");
  assert.equal(h.calls[0]?.url, status.url);
  assert.equal(h.calls[0]?.headers.authorization, undefined);
  golden("status.ok", { content: res.content, ephemeral: false });
});

test("status: names the failing parts from a fixed list only", async () => {
  const h = statusHarness();
  h.clock = Date.UTC(2026, 10, 30, 14, 5);
  h.router = () =>
    json(statusBody({ status: "degraded", database: "error", redis: "<@everyone>", model: "error" }));
  const { content: text } = await ask(h, "status");
  golden("status.degraded", { content: text, ephemeral: false });
  assert.ok(!text.includes("everyone"));
});

test("status: is cached for 30 seconds", async () => {
  const h = statusHarness();
  h.router = () => json(statusBody());
  await ask(h, "status");
  h.clock += 29_000;
  await ask(h, "status");
  assert.equal(h.calls.length, 1);
  h.clock += 2_000;
  await ask(h, "status");
  assert.equal(h.calls.length, 2);
});

for (const [label, router] of [
  ["500", () => json({}, 500)],
  ["network error", () => Promise.reject(new Error("down"))],
  ["wrong shape", () => json({ status: "fine" })],
  ["not json", () => new Response("up", { status: 200 })],
] as const) {
  test(`status: ${label} gives the plain answer with the status page`, async () => {
    const h = statusHarness();
    h.router = router as never;
    golden("status.down", { content: (await ask(h, "status")).content, ephemeral: false });
  });
}

test("status: a service that hangs is cut off inside Discord's three seconds", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const h = statusHarness();
    hang(h);
    const pending = h.send(command("status"));
    const res = await tickUntilDone(pending);
    assert.ok(res.body.data.content.startsWith("We could not get an answer from the status service"));
  } finally {
    mock.timers.reset();
  }
});

test("status: without a status address the command says it is not available", async () => {
  const { status: _omit, ...rest } = statusContent;
  const h = new Harness(undefined, rest as typeof content);
  const res = await h.send(command("status"));
  assert.equal(res.body.data.content, "That command is not available yet.");
  assert.equal(shape(res).ephemeral, true);
  assert.equal(h.calls.length, 0);
});

test("no lookup ever defers or calls Discord", async () => {
  const h = new Harness();
  h.router = () => json(releaseBody());
  await ask(h, "release");
  assert.equal(
    h.calls.filter((c) => hostOf(c.url) === "discord.com" || hostOf(c.url).endsWith(".discord.com")).length,
    0,
  );
});
