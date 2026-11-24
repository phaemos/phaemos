import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { TtlCache } from "../src/cache.ts";
import { UpstreamError, fetchBounded } from "../src/http.ts";
import { clip, clipEscaped, escapeMarkdown, formatDate, notesToPlain } from "../src/text.ts";
import { validateContent } from "../src/validate.ts";
import { checkTree, scan } from "../scripts/check-identifiers.ts";
import { content } from "./helpers.ts";

test("escapeMarkdown neutralises markup, mentions and hidden characters", () => {
  assert.equal(escapeMarkdown("**a** _b_ ~c~ |d| `e`"), "\\*\\*a\\*\\* \\_b\\_ \\~c\\~ \\|d\\| \\`e\\`");
  assert.equal(escapeMarkdown("<@1> <#2> <https://x>"), "\\<@1\\> \\<\\#2\\> \\<https://x\\>");
  assert.equal(escapeMarkdown("# title\n- item"), "\\# title\n\\- item");
  assert.equal(escapeMarkdown("a\u202eb\u200bc\u0007"), "abc");
});

test("clip counts characters rather than bytes and says it cut", () => {
  assert.equal(clip("abc", 5), "abc");
  assert.equal(clip("abcdefgh", 5), "ab...");
  assert.equal(Array.from(clip("😀".repeat(10), 5)).length, 5);
  assert.ok(!clipEscaped("\\*\\*\\*\\*\\*\\*", 5).includes("\\..."));
});

test("notesToPlain drops comments, images, links and tags", () => {
  assert.equal(notesToPlain("<!-- c -->a [t](http://x) <b>b</b>"), "a t b");
  assert.equal(notesToPlain("> [!NOTE]\n> hi"), "NOTE:\n> hi");
});

test("notesToPlain leaves no tag or comment that removing another one put together", () => {
  for (const notes of [
    "<scr<b></b>ipt>x</script>",
    "<!<!---->-- c -->a",
    "[<](u)script>x",
    "[<!--](u) a [-->](u)",
  ]) {
    assert.ok(!notesToPlain(notes).includes("<"), notes);
  }
});

test("formatDate writes the day out and refuses nonsense", () => {
  assert.equal(formatDate("2026-11-30T10:00:00Z"), "30 November 2026");
  assert.equal(formatDate("nonsense"), null);
  assert.equal(formatDate(5), null);
});

test("the cache expires entries and stays bounded", () => {
  const c = new TtlCache<number>(2);
  c.set("a", 1, 0);
  c.set("b", 2, 0);
  c.set("c", 3, 0);
  assert.equal(c.size, 2);
  assert.equal(c.get("a", 1, 10), undefined);
  assert.equal(c.get("c", 5, 10), 3);
  assert.equal(c.get("c", 11, 10), undefined);
});

test("fetchBounded: time-out, size limit and redirects", async () => {
  const slow = (_u: string, init?: RequestInit) =>
    new Promise<Response>((_r, reject) =>
      init?.signal?.addEventListener("abort", () => reject(new Error("x"))),
    );
  await assert.rejects(
    fetchBounded(slow, "https://x.example", {}, { timeoutMs: 20, maxBytes: 10 }),
    (e: unknown) => e instanceof UpstreamError && e.kind === "timeout",
  );
  const big = async () => new Response("x".repeat(100));
  await assert.rejects(
    fetchBounded(big, "https://x.example", {}, { timeoutMs: 100, maxBytes: 10 }),
    (e: unknown) => e instanceof UpstreamError && e.kind === "size",
  );
  const declared = async () => new Response("x", { headers: { "content-length": "9999" } });
  await assert.rejects(
    fetchBounded(declared, "https://x.example", {}, { timeoutMs: 100, maxBytes: 10 }),
    (e: unknown) => e instanceof UpstreamError && e.kind === "size",
  );
  let seen: RequestInit | undefined;
  const ok = async (_u: string, init?: RequestInit) => {
    seen = init;
    return new Response("fine");
  };
  assert.deepEqual(await fetchBounded(ok, "https://x.example", {}, { timeoutMs: 100, maxBytes: 10 }), {
    status: 200,
    body: "fine",
  });
  assert.equal(seen?.redirect, "manual");
});

test("the shipped content passes validation", () => {
  assert.deepEqual(validateContent(content), []);
});

test("validation catches limits and style mistakes", () => {
  const bad = structuredClone(content);
  bad.docs[0]!.lines[0] = "Long \u2014 dash, and comma";
  bad.faq[0]!.lines[1] = `An id ${"1".repeat(18)}`;
  bad.bug.lines[0] = "Smile \u{1F600}";
  bad.hardware[0]!.links[0]!.url = "http://not-secure.example";
  bad.commands[0]!.description = "x".repeat(101);
  bad.docs.push({ ...bad.docs[0]!, lines: ["one"] });
  const problems = validateContent(bad).join("\n");
  for (const expected of [
    "a long dash",
    "a comma before and or or",
    "17 to 20 digits",
    "an emoji",
    "plain https",
    "1 to 100",
    "duplicate",
    "exactly two lines",
  ]) {
    assert.ok(problems.includes(expected), `missing: ${expected}\n${problems}`);
  }
});

test("the identifier check finds each kind of thing and ignores plain text", () => {
  const digits = "9".repeat(18);
  const hex = "ab".repeat(32);
  const samples = [
    `id ${digits}`,
    ["https://discord.com", "api", "webhooks", "1", "x"].join("/"),
    `key ${hex}`,
    `${"M"}${"a".repeat(24)}.${"b".repeat(6)}.${"c".repeat(27)}`,
    `gh${"p"}_${"A".repeat(36)}`,
    `${"-----BEGIN "}PRIVATE KEY-----`,
    `token = "${"a".repeat(30)}"`,
  ];
  for (const s of samples) assert.ok(scan(s).length > 0, s);
  for (const fine of ["issue 412", "version 2.6.0", "1234567890123456", "plain words"])
    assert.deepEqual(scan(fine), [], fine);
  const dir = mkdtempSync(join(tmpdir(), "idcheck-"));
  writeFileSync(join(dir, "a.md"), `leak ${digits}\n`);
  assert.equal(checkTree([dir]).length, 1);
});
