// member reports. what goes to the staff channel is fixed here and nothing else is added:
// who reported, who it is about, where and the reporter's words. the reported message itself is never
// copied: the link is the evidence and staff read the message there.
import { TtlCache } from "./cache.ts";
import { type Json, isRecord, isSnowflake } from "./discord.ts";
import { type FetchLike, UpstreamError, fetchBounded } from "./http.ts";
import { clip, clipEscaped, escapeMarkdown, plain } from "./text.ts";

export const REPORT_TIMEOUT_MS = 2500;
export const REPORT_COOLDOWN_MS = 60 * 1000;
export const MAX_DETAILS = 1000;
export const MAX_MODAL_REASON = 500;
// the form carries the start of the reported message in its own id, which Discord limits to 100
// characters. the worker keeps nothing between the two steps, so that is all there is room for.
const WEBHOOK_HOSTS = new Set(["discord.com", "discordapp.com"]);

export interface ReportEntry {
  reporter: string;
  about: string;
  where: string;
  why: string;
}

export function webhookTarget(value: string | undefined): URL | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    const parts = url.pathname.split("/").filter((s) => s !== "");
    if (url.protocol !== "https:" || !WEBHOOK_HOSTS.has(url.hostname)) return null;
    if (parts[0] !== "api" || !parts.includes("webhooks") || parts.length < 4) return null;
    url.search = "";
    url.hash = "";
    url.searchParams.set("wait", "true");
    return url;
  } catch {
    return null;
  }
}

export function buildEmbedBody(entry: ReportEntry): Json {
  const fields: { name: string; value: string; inline: boolean }[] = [
    { name: "Reported by", value: `<@${entry.reporter}>`, inline: true },
    { name: "About", value: entry.about, inline: true },
    { name: "Where", value: entry.where, inline: false },
  ];
  fields.push({ name: "Why, in the reporter's words, not verified", value: entry.why, inline: false });
  return {
    embeds: [{ title: "Report from a member", fields }],
    allowed_mentions: { parse: [] },
  };
}

export function reasonText(raw: string, max: number): string {
  const cut = Array.from(plain(raw).trim()).slice(0, max).join("");
  return clipEscaped(escapeMarkdown(cut), 1000) || "No words were added";
}

export async function postReport(doFetch: FetchLike, target: URL, entry: ReportEntry): Promise<boolean> {
  try {
    const res = await fetchBounded(
      doFetch,
      target.toString(),
      {
        method: "POST",
        headers: { "content-type": "application/json", "user-agent": "community-commands-worker" },
        body: JSON.stringify(buildEmbedBody(entry)),
      },
      { timeoutMs: REPORT_TIMEOUT_MS, maxBytes: 64 * 1024 },
    );
    return res.status >= 200 && res.status < 300;
  } catch (err) {
    if (!(err instanceof UpstreamError)) throw err;
    return false;
  }
}

// one report a minute for each member, kept in memory. it is best effort: a second isolate has its own list.
export class ReportLimiter {
  private seen = new TtlCache<number>(5000);

  private cooldownMs: number;

  constructor(cooldownMs: number = REPORT_COOLDOWN_MS) {
    this.cooldownMs = cooldownMs;
  }

  tryTake(member: string, now: number): boolean {
    if (this.seen.get(member, now, this.cooldownMs) !== undefined) return false;
    this.seen.set(member, now, now);
    return true;
  }

  giveBack(member: string): void {
    this.seen.delete(member);
  }
}

// the form's id is r|<message id>. Discord hands a form's id back from the reporter's own app, so it is
// treated as a claim: only a well-formed message id is accepted and nothing else travels in it.
export function buildModalId(messageId: string): string {
  return `r|${messageId}`;
}

export function parseModalId(id: string): { messageId: string } | null {
  const parts = id.split("|");
  const [tag, messageId] = parts;
  if (parts.length !== 2 || tag !== "r" || !isSnowflake(messageId)) return null;
  return { messageId };
}

// the text the member typed in the form, wherever the form puts it.
export function modalValue(components: unknown, customId: string, depth = 0): string | undefined {
  if (!Array.isArray(components) || depth > 3) return undefined;
  for (const c of components) {
    if (!isRecord(c)) continue;
    if (c.custom_id === customId && typeof c.value === "string") return c.value;
    const inner = modalValue(Array.isArray(c.components) ? c.components : [c.component], customId, depth + 1);
    if (inner !== undefined) return inner;
  }
  return undefined;
}

export function modalDefinition(customId: string, contact: string): Json {
  return {
    type: 9,
    data: {
      custom_id: customId,
      title: "Report to moderators",
      components: [
        {
          type: 18,
          label: "What is wrong?",
          description: clip(
            `Every moderator sees this and your name. To report staff, email ${contact}`,
            100,
          ),
          component: { type: 4, custom_id: "why", style: 2, required: false, max_length: MAX_MODAL_REASON },
        },
      ],
    },
  };
}
