// shared test tools. keys are made fresh for each run and never written anywhere.
import assert from "node:assert/strict";
import { generateKeyPairSync, sign } from "node:crypto";
import { readFileSync } from "node:fs";
import { createApp, type Env } from "../src/app.ts";
import type { Content } from "../src/content.ts";

export const content = JSON.parse(
  readFileSync(new URL("../src/content.generated.json", import.meta.url), "utf8"),
) as Content;

// ids are built at run time so that no file holds a literal one.
export function id(n: number): string {
  return `9${String(n).padStart(17, "0")}`;
}
export const GUILD = id(1);
export const CHANNEL = id(2);
export const APP = id(3);
export const ALICE = id(10);
export const BOB = id(11);
export const MESSAGE = id(20);
export const TOKEN = "t".repeat(40);

const pair = generateKeyPairSync("ed25519");
const otherPair = generateKeyPairSync("ed25519");
const publicHex = (k: typeof pair): string =>
  Buffer.from(k.publicKey.export({ format: "der", type: "spki" }).subarray(-32)).toString("hex");

export const PUBLIC_KEY = publicHex(pair);

export function signBody(timestamp: string, body: string | Uint8Array, wrongKey = false): string {
  const bytes = typeof body === "string" ? Buffer.from(body) : Buffer.from(body);
  const message = Buffer.concat([Buffer.from(timestamp), bytes]);
  return sign(null, message, (wrongKey ? otherPair : pair).privateKey).toString("hex");
}

export interface Call {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: string | null;
}

export type Router = (call: Call) => Response | Promise<Response>;

// built at run time so that no file holds something shaped like a webhook address.
export const WEBHOOK = ["https://discord.com", "api", "webhooks", "1", "test-only"].join("/");

export function makeEnv(extra: Partial<Env> = {}): Env {
  return {
    DISCORD_PUBLIC_KEY: PUBLIC_KEY,
    REPORTS_WEBHOOK_URL: WEBHOOK,
    PROJECT: content.project.slug,
    ...extra,
  };
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

export class Harness {
  clock = Date.now();
  calls: Call[] = [];
  pending: Promise<unknown>[] = [];
  router: Router = () => new Response("unexpected", { status: 500 });
  app: ReturnType<typeof createApp>;
  env: Env;

  constructor(env: Env = makeEnv(), c: Content = content) {
    this.env = env;
    this.app = createApp(c, {
      now: () => this.clock,
      doFetch: async (url, init) => {
        const headers: Record<string, string> = {};
        new Headers(init?.headers).forEach((v, k) => {
          headers[k] = v;
        });
        const call: Call = {
          url,
          method: init?.method ?? "GET",
          headers,
          body: typeof init?.body === "string" ? init.body : null,
        };
        this.calls.push(call);
        const signal = init?.signal;
        const result = Promise.resolve(this.router(call));
        if (!signal) return result;
        return new Promise<Response>((resolve, reject) => {
          signal.addEventListener("abort", () => reject(new Error("aborted")));
          result.then(resolve, reject);
        });
      },
    });
  }

  ctx = {
    waitUntil: (p: Promise<unknown>) => {
      this.pending.push(p);
    },
  };

  async settle(): Promise<void> {
    await Promise.all(this.pending);
    this.pending = [];
  }

  signedRequest(
    body: string | Uint8Array,
    opts: { timestamp?: string; signature?: string; path?: string } = {},
  ): Request {
    const timestamp = opts.timestamp ?? String(Math.floor(this.clock / 1000));
    const signature = opts.signature ?? signBody(timestamp, body);
    return new Request(`https://worker.example/${opts.path ?? "interactions"}`, {
      method: "POST",
      headers: {
        "x-signature-ed25519": signature,
        "x-signature-timestamp": timestamp,
        "content-type": "application/json",
      },
      body: body as BodyInit,
    });
  }

  async send(interaction: unknown): Promise<{ status: number; body: any }> {
    const res = await this.app.fetch(this.signedRequest(JSON.stringify(interaction)), this.env, this.ctx);
    const body = res.headers.get("content-type")?.includes("json") ? await res.json() : await res.text();
    if (res.status === 200 && body && typeof body === "object" && (body.type === 4 || body.type === 5)) {
      assertSafeMessage(body.data);
    }
    return { status: res.status, body };
  }
}

const COMMA_JOINER = /,\s+(and|or)\b/i;
const DASH = /[‒-―]/;
const EMOJI = /\p{Extended_Pictographic}/u;

// every message the worker sends must pass these, whatever test sent the command.
export function assertSafeMessage(data: any): void {
  assert.deepEqual(data.allowed_mentions, { parse: [] }, "mentions must be off");
  assert.equal(data.flags & 4, 4, "link previews must be off");
  assert.equal(data.embeds, undefined, "no embeds");
  if (typeof data.content === "string") {
    assert.ok(data.content.length <= 2000, "content within Discord's limit");
    assert.ok(!COMMA_JOINER.test(data.content), `comma before and or or: ${data.content}`);
    assert.ok(!DASH.test(data.content), "no long dash");
    assert.ok(!EMOJI.test(data.content), "no emoji");
  }
}

export function command(
  name: string,
  options: { name: string; type: number; value: unknown }[] = [],
  opts: {
    permissions?: string;
    guild?: boolean;
    type?: number;
    extra?: Record<string, unknown>;
    user?: string;
    roles?: string[];
  } = {},
): Record<string, unknown> {
  const base: Record<string, unknown> = {
    type: 2,
    application_id: APP,
    token: TOKEN,
    channel_id: CHANNEL,
    data: { id: id(99), name, type: opts.type ?? 1, options, ...(opts.extra ?? {}) },
  };
  if (opts.guild !== false) {
    base.guild_id = GUILD;
    base.member = {
      permissions: opts.permissions ?? "311452355648",
      roles: opts.roles ?? [],
      user: { id: opts.user ?? ALICE },
    };
  } else {
    base.user = { id: opts.user ?? ALICE };
  }
  return base;
}

export const STAFF = "2252899459538944";
export const str = (name: string, value: string) => ({ name, type: 3, value });
export const int = (name: string, value: number) => ({ name, type: 4, value });
export const bool = (name: string, value: boolean) => ({ name, type: 5, value });
export const user = (name: string, value: string) => ({ name, type: 6, value });

// golden answers: the exact text each command gives. run with UPDATE_GOLDEN=1 to rewrite the file,
// then read the diff.
import { existsSync, writeFileSync } from "node:fs";
const goldenPath = new URL("./golden.json", import.meta.url);
const goldenData: Record<string, unknown> = existsSync(goldenPath)
  ? JSON.parse(readFileSync(goldenPath, "utf8"))
  : {};
const goldenSeen: Record<string, unknown> = {};

export function golden(name: string, actual: unknown): void {
  goldenSeen[name] = actual;
  if (process.env.UPDATE_GOLDEN === "1") {
    const merged = { ...goldenData, ...goldenSeen };
    const sorted = Object.fromEntries(Object.entries(merged).sort(([a], [b]) => a.localeCompare(b)));
    writeFileSync(goldenPath, `${JSON.stringify(sorted, null, 2)}\n`);
    return;
  }
  assert.ok(name in goldenData, `no golden answer for ${name}. run with UPDATE_GOLDEN=1`);
  assert.deepEqual(actual, goldenData[name], `golden answer changed: ${name}`);
}

export function shape(res: { body: any }): { content: string; ephemeral: boolean } {
  return { content: res.body.data.content, ephemeral: (res.body.data.flags & 64) === 64 };
}
