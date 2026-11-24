// the three answers that need another service: the latest release, an issue and the service status.
import { TtlCache } from "./cache.ts";
import type { Answer } from "./discord.ts";
import { type FetchLike, UpstreamError, fetchBounded, parseJson } from "./http.ts";
import { clip, escapeMarkdown, formatDate, formatTime, notesToPlain, oneLine } from "./text.ts";
import type { Content } from "./content.ts";

const GITHUB_API = "https://api.github.com";
const REPO_SHAPE = /^[A-Za-z0-9_.-]{1,100}\/[A-Za-z0-9_.-]{1,100}$/;

export const MAX_ISSUE_NUMBER = 99999999;

// how long each answer is kept. stale answers are served only when the service is down.
export const RELEASE_TTL_MS = 10 * 60 * 1000;
export const ISSUE_TTL_MS = 5 * 60 * 1000;
export const STATUS_TTL_MS = 30 * 1000;
export const STALE_MS = 60 * 60 * 1000;
export const GITHUB_TIMEOUT_MS = 2200;
export const STATUS_TIMEOUT_MS = 2200;
const GITHUB_MAX_BYTES = 512 * 1024;
const STATUS_MAX_BYTES = 16 * 1024;

export interface Lookup {
  key: string;
  ttlMs: number;
  run: () => Promise<Answer>;
  fallback: () => Answer;
}

export interface LookupDeps {
  doFetch: FetchLike;
  now: () => number;
  githubToken?: string | undefined;
}

export class LookupCache {
  private answers = new TtlCache<Answer>(200);
  private inflight = new Map<string, Promise<Answer>>();

  fresh(key: string, now: number, ttlMs: number): Answer | undefined {
    return this.answers.get(key, now, ttlMs);
  }

  // one call upstream for any number of identical commands that arrive together.
  async execute(lookup: Lookup, now: () => number): Promise<Answer> {
    const running = this.inflight.get(lookup.key);
    if (running) return running;
    const job = (async () => {
      try {
        const answer = await lookup.run();
        this.answers.set(lookup.key, answer, now());
        return answer;
      } catch (err) {
        if (!(err instanceof UpstreamError)) console.log(JSON.stringify({ event: "lookup_bug" }));
        const stale = this.answers.get(lookup.key, now(), STALE_MS);
        return stale ?? lookup.fallback();
      } finally {
        this.inflight.delete(lookup.key);
      }
    })();
    this.inflight.set(lookup.key, job);
    return job;
  }
}

function githubHeaders(token?: string): Record<string, string> {
  const headers: Record<string, string> = {
    accept: "application/vnd.github+json",
    "user-agent": "community-commands-worker",
    "x-github-api-version": "2022-11-28",
  };
  if (token) headers.authorization = `Bearer ${token}`;
  return headers;
}

// returns null for a 404 and throws for anything else that is not a 200.
async function githubGet(deps: LookupDeps, path: string): Promise<Record<string, unknown> | null> {
  const res = await fetchBounded(
    deps.doFetch,
    `${GITHUB_API}${path}`,
    { method: "GET", headers: githubHeaders(deps.githubToken) },
    { timeoutMs: GITHUB_TIMEOUT_MS, maxBytes: GITHUB_MAX_BYTES },
  );
  if (res.status === 404) return null;
  if (res.status !== 200) throw new UpstreamError("status", res.status);
  const json = parseJson(res.body);
  if (typeof json !== "object" || json === null || Array.isArray(json)) throw new UpstreamError("parse");
  return json as Record<string, unknown>;
}

function repoPath(repository: string): string {
  if (!REPO_SHAPE.test(repository)) throw new UpstreamError("parse");
  const [owner = "", repo = ""] = repository.split("/");
  return `/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`;
}

export function releaseLookup(content: Content, deps: LookupDeps): Lookup {
  const p = content.project;
  return {
    key: "release",
    ttlMs: RELEASE_TTL_MS,
    fallback: () => ({
      content: `We could not reach GitHub just now. The releases are at <${p.releases}>`,
      ephemeral: false,
    }),
    run: async () => {
      const data = await githubGet(deps, `${repoPath(p.repository)}/releases/latest`);
      if (data === null) {
        return {
          content: "There is no release yet. We will post each new one in releases.",
          ephemeral: false,
        };
      }
      const tag = typeof data.tag_name === "string" ? oneLine(data.tag_name) : "";
      if (!tag) throw new UpstreamError("parse");
      const date = formatDate(data.published_at);
      const body = typeof data.body === "string" ? data.body : "";
      const notes = clip(notesToPlain(body), 600)
        .split("\n")
        .slice(0, 12)
        .map((line) => `> ${escapeMarkdown(line)}`)
        .join("\n");
      const link = `${p.site}/releases/tag/${encodeURIComponent(tag)}`;
      const head = `Latest release: ${escapeMarkdown(tag.slice(0, 64))}${date ? ` (published ${date})` : ""}`;
      return {
        content: [head, notes, `Full notes: <${link}>`].filter((s) => s !== "").join("\n"),
        ephemeral: false,
      };
    },
  };
}

export function issueLookup(content: Content, deps: LookupDeps, number: number): Lookup {
  const p = content.project;
  const link = `${p.site}/issues/${number}`;
  return {
    key: `issue:${number}`,
    ttlMs: ISSUE_TTL_MS,
    fallback: () => ({
      content: `We could not reach GitHub just now. Issue ${number} is at <${link}>`,
      ephemeral: false,
    }),
    run: async () => {
      const data = await githubGet(deps, `${repoPath(p.repository)}/issues/${number}`);
      if (data === null) return { content: `We could not find number ${number}.`, ephemeral: true };
      const pull = data.pull_request;
      const isPull = typeof pull === "object" && pull !== null;
      let state = data.state === "open" ? "open" : "closed";
      if (isPull && state === "closed") {
        const merged = (pull as Record<string, unknown>).merged_at;
        if (typeof merged === "string") state = "merged";
      }
      const title = escapeMarkdown(clip(oneLine(typeof data.title === "string" ? data.title : ""), 200));
      const labels = Array.isArray(data.labels)
        ? data.labels
            .map((l) => (typeof l === "object" && l !== null ? (l as Record<string, unknown>).name : l))
            .filter((n): n is string => typeof n === "string")
            .slice(0, 10)
            .map((n) => escapeMarkdown(clip(oneLine(n), 50)))
        : [];
      const lines = [`${isPull ? "Pull request" : "Issue"} ${number} (${state}): ${title}`];
      if (labels.length > 0) lines.push(`Labels: ${labels.join(", ")}`);
      lines.push(`<${link}>`);
      return { content: lines.join("\n"), ephemeral: false };
    },
  };
}

const PARTS = ["database", "redis", "model"] as const;

export function statusLookup(content: Content, deps: LookupDeps): Lookup | null {
  const status = content.status;
  if (!status) return null;
  return {
    key: "status",
    ttlMs: STATUS_TTL_MS,
    fallback: () => ({
      content: `We could not get an answer from the status service just now. The service may not be live yet or may itself be the problem. The status page is at <${status.page}>`,
      ephemeral: false,
    }),
    run: async () => {
      const res = await fetchBounded(
        deps.doFetch,
        status.url,
        { method: "GET", headers: { accept: "application/json", "user-agent": "community-commands-worker" } },
        { timeoutMs: STATUS_TIMEOUT_MS, maxBytes: STATUS_MAX_BYTES },
      );
      if (res.status !== 200) throw new UpstreamError("status", res.status);
      const json = parseJson(res.body);
      if (typeof json !== "object" || json === null) throw new UpstreamError("parse");
      const data = json as Record<string, unknown>;
      if (data.status !== "operational" && data.status !== "degraded") throw new UpstreamError("parse");
      const at = formatTime(deps.now());
      if (data.status === "operational") {
        return { content: `All systems are working. Checked at ${at}.`, ephemeral: false };
      }
      // only fixed words from our own list are shown, never text that came from the service.
      const failing = PARTS.filter((part) => data[part] === "error");
      const which = failing.length > 0 ? failing.join(", ") : "one part";
      return {
        content: `Some parts are not working: ${which}. Checked at ${at}. The status page is at <${status.page}>`,
        ephemeral: false,
      };
    },
  };
}
