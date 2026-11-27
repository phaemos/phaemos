// a ticket is a private matter. the member's words go to the staff forum through a webhook and are never
// repeated in a message anyone else can read. the worker holds a webhook address and no bot token.
import { type Json, isSnowflake } from "./discord.ts";
import { type FetchLike, UpstreamError, fetchBounded } from "./http.ts";
import { REPORT_TIMEOUT_MS, modalValue, webhookTarget } from "./report.ts";
import { clip, clipEscaped, escapeMarkdown, oneLine, plain } from "./text.ts";

export const TICKET_COOLDOWN_MS = 10 * 60 * 1000;
export const TICKET_DEDUPE_MS = 5 * 60 * 1000;
export const MAX_SUBJECT = 90;
export const MAX_TICKET_DETAILS = 1000;

export interface TicketKind {
  key: string;
  title: string;
}

export interface Ticket {
  member: string;
  kind: TicketKind;
  subject: string;
  details: string;
}

export function buildTicketModalId(kind: string): string {
  return `t|${kind}`;
}

// the form's id is handed back by the member's own app, so it is a claim: the kind must be one we list.
export function parseTicketModalId(id: string, kinds: TicketKind[]): TicketKind | null {
  const parts = id.split("|");
  if (parts.length !== 2 || parts[0] !== "t") return null;
  return kinds.find((k) => k.key === parts[1]) ?? null;
}

export function ticketModal(kind: TicketKind, contact: string): Json {
  return {
    type: 9,
    data: {
      custom_id: buildTicketModalId(kind.key),
      title: clip(`Ticket: ${kind.title}`, 45),
      components: [
        {
          type: 18,
          label: "Subject",
          description: clip("A few words. Only the staff can read your ticket.", 100),
          component: {
            type: 4,
            custom_id: "subject",
            style: 1,
            required: true,
            min_length: 1,
            max_length: MAX_SUBJECT,
          },
        },
        {
          type: 18,
          label: "Details",
          description: clip(`To report a member of staff, email ${contact}`, 100),
          component: {
            type: 4,
            custom_id: "details",
            style: 2,
            required: true,
            min_length: 1,
            max_length: MAX_TICKET_DETAILS,
          },
        },
      ],
    },
  };
}

// what the member typed. null when the form is empty or too long. an empty form is refused, not posted.
export function readTicketForm(components: unknown): { subject: string; details: string } | null {
  const subject = oneLine(modalValue(components, "subject") ?? "");
  const details = plain(modalValue(components, "details") ?? "").trim();
  if (subject === "" || details === "") return null;
  if (Array.from(subject).length > MAX_SUBJECT || Array.from(details).length > MAX_TICKET_DETAILS)
    return null;
  return { subject, details };
}

// a forum post needs a thread name. the tag ids come from a secret that lists kind:id pairs. without it the
// kind is still in the post's name and its text.
export function parseTagIds(value: string | undefined): Map<string, string> {
  const map = new Map<string, string>();
  for (const pair of (value ?? "").split(",")) {
    const [key, tag] = pair.split(":").map((s) => s.trim());
    if (key && isSnowflake(tag)) map.set(key, tag);
  }
  return map;
}

export function buildTicketBody(ticket: Ticket, tags: Map<string, string>): Json {
  const tag = tags.get(ticket.kind.key);
  const body: Json = {
    thread_name: clip(`${ticket.kind.title}: ${ticket.subject}`, 100),
    embeds: [
      {
        title: "Ticket from a member",
        fields: [
          { name: "From", value: `<@${ticket.member}>`, inline: true },
          { name: "Kind", value: ticket.kind.title, inline: true },
          { name: "Status", value: "Open", inline: true },
          { name: "Subject", value: clipEscaped(escapeMarkdown(ticket.subject), 200), inline: false },
          {
            name: "Details, in the member's words",
            value: clipEscaped(escapeMarkdown(ticket.details), 1000),
            inline: false,
          },
        ],
      },
    ],
    // nothing a member types can ping anyone
    allowed_mentions: { parse: [] },
  };
  if (tag) body.applied_tags = [tag];
  return body;
}

// "sent": Discord made the post. "refused": it certainly did not (no usable address or an answer in the 4xx range).
// "unknown": a timeout, a network error or a 5xx, where Discord may still have made the post
export type PostOutcome = "sent" | "refused" | "unknown";

export async function postTicket(
  doFetch: FetchLike,
  address: string | undefined,
  ticket: Ticket,
  tagIds: string | undefined,
): Promise<PostOutcome> {
  const target = webhookTarget(address);
  if (!target) return "refused";
  try {
    const res = await fetchBounded(
      doFetch,
      target.toString(),
      {
        method: "POST",
        headers: { "content-type": "application/json", "user-agent": "community-commands-worker" },
        body: JSON.stringify(buildTicketBody(ticket, parseTagIds(tagIds))),
      },
      { timeoutMs: REPORT_TIMEOUT_MS, maxBytes: 64 * 1024 },
    );
    if (res.status >= 200 && res.status < 300) return "sent";
    return res.status >= 400 && res.status < 500 ? "refused" : "unknown";
  } catch (err) {
    if (!(err instanceof UpstreamError)) throw err;
    return "unknown";
  }
}
