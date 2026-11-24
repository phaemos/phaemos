// the request path. every request is hostile until its signature verifies, so the order is fixed:
// route, headers, size, timestamp and signature. only then the body is parsed.
import { TtlCache } from "./cache.ts";
import type { CommandDef, Content, Topic } from "./content.ts";
import {
  type Answer,
  type Json,
  TYPE_COMMAND,
  TYPE_MODAL_SUBMIT,
  TYPE_PING,
  findOption,
  isRecord,
  isSnowflake,
  isStaffMember,
  parseStaffRoles,
  jsonResponse,
  reply,
  str,
  subcommandName,
} from "./discord.ts";
import type { FetchLike } from "./http.ts";
import {
  type Lookup,
  LookupCache,
  type LookupDeps,
  MAX_ISSUE_NUMBER,
  issueLookup,
  releaseLookup,
  statusLookup,
} from "./lookups.ts";
import {
  MAX_DETAILS,
  MAX_MODAL_REASON,
  ReportLimiter,
  buildModalId,
  modalDefinition,
  modalValue,
  parseModalId,
  postReport,
  reasonText,
  webhookTarget,
} from "./report.ts";
import {
  TICKET_COOLDOWN_MS,
  TICKET_DEDUPE_MS,
  MAX_SUBJECT,
  MAX_TICKET_DETAILS,
  parseTicketModalId,
  postTicket,
  readTicketForm,
  ticketModal,
} from "./ticket.ts";
import { oneLine } from "./text.ts";
import { isValidPublicKey, verifySignature } from "./verify.ts";

export interface Env {
  DISCORD_PUBLIC_KEY?: string;
  REPORTS_WEBHOOK_URL?: string;
  PROJECT?: string;
  GITHUB_TOKEN?: string;
  STAFF_ROLE_IDS?: string;
  TICKETS_WEBHOOK_URL?: string;
  TICKET_TAG_IDS?: string;
}

export interface ExecutionContextLike {
  waitUntil(promise: Promise<unknown>): void;
}

export interface AppDeps {
  doFetch: FetchLike;
  now: () => number;
}

// limits we chose. Discord's page states none of them.
export const MAX_BODY_BYTES = 128 * 1024;
export const MAX_TIMESTAMP_SKEW_SECONDS = 300;

const UNKNOWN: Answer = { content: "We do not know that command. Type /help.", ephemeral: true };
const GUILD_ONLY: Answer = { content: "These commands work inside the server only.", ephemeral: true };
const STAFF_ONLY: Answer = { content: "That command is for the moderators.", ephemeral: true };
const FAILED: Answer = { content: "Something went wrong on our side. Please try again.", ephemeral: true };

function text(body: string, status: number): Response {
  return new Response(body, {
    status,
    headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" },
  });
}

function topicAnswer(topic: Topic): string {
  const links = topic.links.map((l) => `${l.label}: <${l.url}>`);
  return [topic.title, ...topic.lines, ...links].join("\n");
}

function block(lines: string[], links: { label: string; url: string }[]): string {
  return [...lines, ...links.map((l) => `${l.label}: <${l.url}>`)].join("\n");
}

function log(name: string, outcome: string, started: number, now: () => number): void {
  // the command name and the outcome only. never a member, a channel or any text they typed.
  console.log(JSON.stringify({ event: "command", name, outcome, ms: now() - started }));
}

export function createApp(content: Content, deps: AppDeps) {
  const cache = new LookupCache();
  const limiter = new ReportLimiter();
  const ticketLimiter = new ReportLimiter(TICKET_COOLDOWN_MS);
  // an interaction id seen in the last five minutes is a redelivery of the same form, which must not post twice
  const ticketsSeen = new TtlCache<boolean>(2000);
  const commands = new Map<string, CommandDef>();
  for (const c of content.commands) commands.set(`${c.type === "message" ? "m" : "c"}:${c.name}`, c);

  function pick(list: Topic[], key: unknown): Topic | undefined {
    return typeof key === "string" ? list.find((t) => t.key === key) : undefined;
  }

  // an address is never a link in Discord, so a page that names it follows it
  function contactWays(): string {
    const page = content.project.contact_page;
    return page ? `${content.project.contact_email} or see <${page}>` : content.project.contact_email;
  }

  function helpAnswer(staff: boolean): Answer {
    const lines = ["Our commands:"];
    for (const c of content.commands) {
      if (!c.help || (c.staff && !staff)) continue;
      lines.push(c.type === "message" ? `${c.name} - ${c.help}` : `/${c.name} - ${c.help}`);
    }
    const where = content.project.commands_channel;
    if (where) lines.push(`You can try them in #${where}.`);
    return { content: lines.join("\n"), ephemeral: false };
  }

  function modAnswer(data: Json): Answer {
    const sub = subcommandName(data);
    if (sub === "guide") {
      const guide = content.mod_guide.find((g) => g.key === findOption(data, "topic"));
      if (!guide) return UNKNOWN;
      return {
        content: [guide.title, ...guide.steps.map((s, i) => `${i + 1}. ${s}`)].join("\n"),
        ephemeral: true,
      };
    }
    if (sub === "reply") {
      const found = content.mod_reply.find((r) => r.key === findOption(data, "template"));
      if (!found) return UNKNOWN;
      return { content: `From the moderators: ${found.text}`, ephemeral: false };
    }
    return UNKNOWN;
  }

  function staticAnswer(name: string, data: Json): Answer | null {
    switch (name) {
      case "help":
        return null;
      case "docs":
      case "faq":
      case "hardware": {
        const list = name === "docs" ? content.docs : name === "faq" ? content.faq : content.hardware;
        const topic = pick(list, findOption(data, name === "hardware" ? "part" : "topic"));
        if (!topic) return { content: "We do not have that topic. Type /help.", ephemeral: true };
        return { content: topicAnswer(topic), ephemeral: false };
      }
      case "security":
        return {
          content: [
            ...content.security.lines,
            ...content.security.links.map((l) => `${l.label}: <${l.url}>`),
            `Email: ${content.security.email}`,
          ].join("\n"),
          ephemeral: false,
        };
      case "contribute":
        return { content: block(content.contribute.lines, content.contribute.links), ephemeral: false };
      case "roles":
        return { content: block(content.roles.lines, content.roles.links), ephemeral: false };
      default:
        return null;
    }
  }

  // an answer marked private stays private. otherwise the share switch decides and the command's own
  // default applies when the member left it out.
  function visibleTo(def: CommandDef, data: Json, answer: Answer): Answer {
    if (answer.ephemeral) return answer;
    const share = findOption(data, "share");
    return { ...answer, ephemeral: typeof share === "boolean" ? !share : def.visibility === "private" };
  }

  function lookupFor(name: string, data: Json, env: Env): Lookup | null | "bad" {
    const lookupDeps: LookupDeps = { doFetch: deps.doFetch, now: deps.now, githubToken: env.GITHUB_TOKEN };
    if (name === "release") return releaseLookup(content, lookupDeps);
    if (name === "status") return statusLookup(content, lookupDeps);
    if (name === "issue" && subcommandName(data) === "show") {
      const n = findOption(data, "number");
      if (typeof n !== "number" || !Number.isSafeInteger(n) || n < 1 || n > MAX_ISSUE_NUMBER) return "bad";
      return issueLookup(content, lookupDeps, n);
    }
    return null;
  }

  // a lookup is answered in the same request with a short time-out, so the answer is public or private from
  // the start. Discord cannot change a reply's visibility once the reply has been deferred.
  async function handleLookup(name: string, def: CommandDef, data: Json, env: Env): Promise<Response> {
    const lookup = lookupFor(name, data, env);
    if (lookup === "bad")
      return reply({ content: "Please give an issue number between 1 and 99999999.", ephemeral: true });
    if (lookup === null) return reply({ content: "That command is not available yet.", ephemeral: true });
    const hit = cache.fresh(lookup.key, deps.now(), lookup.ttlMs);
    const answer = hit ?? (await cache.execute(lookup, deps.now));
    return reply(visibleTo(def, data, answer));
  }

  async function submitReport(
    entry: { reporter: string; about: string; where: string; why: string },
    env: Env,
    now: number,
  ): Promise<Answer> {
    const failed: Answer = {
      content: `We could not record your report. Please write to ${contactWays()}`,
      ephemeral: true,
    };
    if (!limiter.tryTake(entry.reporter, now)) {
      return { content: "Please wait a minute before sending another report.", ephemeral: true };
    }
    const target = webhookTarget(env.REPORTS_WEBHOOK_URL);
    if (!target) {
      limiter.giveBack(entry.reporter);
      return failed;
    }
    const ok = await postReport(deps.doFetch, target, entry);
    if (!ok) {
      limiter.giveBack(entry.reporter);
      return failed;
    }
    return {
      content: `Thank you. Every moderator can see your report and your name. To report a member of staff, write to ${contactWays()}.`,
      ephemeral: true,
    };
  }

  function reporterId(i: Json): string | null {
    const member = isRecord(i.member) ? i.member : null;
    const user = member && isRecord(member.user) ? member.user : isRecord(i.user) ? i.user : null;
    return user && isSnowflake(user.id) ? user.id : null;
  }

  async function handleCommand(
    i: Json,
    env: Env,
  ): Promise<{ name: string; outcome: string; response: Response }> {
    const data = isRecord(i.data) ? i.data : null;
    const name = data ? str(data.name) : undefined;
    if (!data || !name) return { name: "unknown", outcome: "bad", response: reply(UNKNOWN) };
    const kind = data.type === 3 ? "m" : "c";
    const def = commands.get(`${kind}:${name}`);
    if (!def) return { name: "unknown", outcome: "unknown", response: reply(UNKNOWN) };
    if (!isSnowflake(i.guild_id)) return { name, outcome: "no_guild", response: reply(GUILD_ONLY) };
    const member = isRecord(i.member) ? i.member : null;
    const staff = isStaffMember(member, parseStaffRoles(env.STAFF_ROLE_IDS));
    // the permission is checked here even though the command is registered for staff only.
    if (def.staff && !staff) return { name, outcome: "denied", response: reply(STAFF_ONLY) };

    if (kind === "m") {
      const target = data.target_id;
      if (!isSnowflake(target)) return { name, outcome: "bad", response: reply(UNKNOWN) };
      const id = buildModalId(target);
      return {
        name,
        outcome: "form",
        response: jsonResponse(modalDefinition(id, content.project.contact_email)),
      };
    }

    if (name === "help")
      return { name, outcome: "ok", response: reply(visibleTo(def, data, helpAnswer(staff))) };
    if (name === "mod") {
      return { name, outcome: "ok", response: reply(modAnswer(data)) };
    }
    if (name === "issue" && subcommandName(data) === "new") {
      const share = findOption(data, "share");
      return {
        name,
        outcome: "ok",
        response: reply({
          content: [
            `${content.bug.lines.join("\n")}`,
            ...content.bug.links.map((l) => `${l.label}: <${l.url}>`),
          ].join("\n"),
          // new issue help is private unless the member asks to share it
          ephemeral: share !== true,
        }),
      };
    }
    if (name === "issue" && subcommandName(data) !== "show") {
      return { name, outcome: "bad", response: reply(UNKNOWN) };
    }
    if (name === "ticket") {
      const kind = content.ticket_kinds.find((k) => k.key === findOption(data, "kind"));
      const member = reporterId(i);
      if (!kind || !member) {
        return { name, outcome: "bad", response: reply(UNKNOWN) };
      }
      return {
        name,
        outcome: "form",
        response: jsonResponse(ticketModal(kind, content.project.contact_email)),
      };
    }
    if (name === "release" || name === "status" || name === "issue") {
      const response = await handleLookup(name, def, data, env);
      return { name, outcome: "ok", response };
    }
    if (name === "report") {
      const reporter = reporterId(i);
      const details = findOption(data, "details");
      if (
        !reporter ||
        typeof details !== "string" ||
        oneLine(details) === "" ||
        Array.from(details).length > MAX_DETAILS
      ) {
        return {
          name,
          outcome: "bad",
          response: reply({
            content: `Please describe the problem in 1 to ${MAX_DETAILS} characters.`,
            ephemeral: true,
          }),
        };
      }
      const about = findOption(data, "member");
      const channel = i.channel_id;
      const answer = await submitReport(
        {
          reporter,
          about: isSnowflake(about) ? `<@${about}>` : "No member named",
          where: isSnowflake(channel) ? `<#${channel}>` : "Not known",
          why: reasonText(details, MAX_DETAILS),
        },
        env,
        deps.now(),
      );
      return {
        name,
        outcome: answer.content.startsWith("Thank you") ? "ok" : "failed",
        response: reply(answer),
      };
    }

    const answer = staticAnswer(name, data);
    if (!answer) return { name, outcome: "unknown", response: reply(UNKNOWN) };
    return { name, outcome: "ok", response: reply(visibleTo(def, data, answer)) };
  }

  async function handleTicket(
    i: Json,
    env: Env,
  ): Promise<{ name: string; outcome: string; response: Response }> {
    const name = "ticket";
    const data = isRecord(i.data) ? i.data : null;
    const kind =
      data && typeof data.custom_id === "string"
        ? parseTicketModalId(data.custom_id, content.ticket_kinds)
        : null;
    const member = reporterId(i);
    if (!data || !kind || !member || !isSnowflake(i.guild_id)) {
      return { name, outcome: "bad", response: reply(UNKNOWN) };
    }
    const form = readTicketForm(data.components);
    if (!form) {
      return {
        name,
        outcome: "bad",
        response: reply({
          content: `Please give a subject of 1 to ${MAX_SUBJECT} characters and details of 1 to ${MAX_TICKET_DETAILS} characters.`,
          ephemeral: true,
        }),
      };
    }
    const interactionId = isSnowflake(i.id) ? i.id : "";
    if (interactionId && ticketsSeen.get(interactionId, deps.now(), TICKET_DEDUPE_MS)) {
      return {
        name,
        outcome: "ok",
        response: reply({ content: content.ticket.lines.join("\n"), ephemeral: true }),
      };
    }
    if (!ticketLimiter.tryTake(member, deps.now())) {
      return {
        name,
        outcome: "limited",
        response: reply({
          content: "Please wait ten minutes before opening another ticket.",
          ephemeral: true,
        }),
      };
    }
    if (interactionId) ticketsSeen.set(interactionId, true, deps.now());
    const outcome = await postTicket(
      deps.doFetch,
      env.TICKETS_WEBHOOK_URL,
      { member, kind, subject: form.subject, details: form.details },
      env.TICKET_TAG_IDS,
    );
    if (outcome !== "sent") {
      // the cooldown is given back only when the post certainly did not happen. After a timeout it may have, and a
      // second try would then make a second ticket
      if (outcome === "refused") ticketLimiter.giveBack(member);
      return {
        name,
        outcome: "failed",
        response: reply({
          content:
            outcome === "refused"
              ? `We could not open your ticket. Please write to ${contactWays()}.`
              : `We could not tell whether your ticket was opened. Please wait ten minutes, then write to ${contactWays()} if you hear nothing.`,
          ephemeral: true,
        }),
      };
    }
    // the member's own words are never repeated here, in public or in private
    return {
      name,
      outcome: "ok",
      response: reply({ content: content.ticket.lines.join("\n"), ephemeral: true }),
    };
  }

  async function handleModal(
    i: Json,
    env: Env,
  ): Promise<{ name: string; outcome: string; response: Response }> {
    const id = isRecord(i.data) && typeof i.data.custom_id === "string" ? i.data.custom_id : "";
    if (id.startsWith("t|")) return handleTicket(i, env);
    const name = "Report to moderators";
    const data = isRecord(i.data) ? i.data : null;
    const parsed = data && typeof data.custom_id === "string" ? parseModalId(data.custom_id) : null;
    const reporter = reporterId(i);
    if (!data || !parsed || !reporter || !isSnowflake(i.guild_id) || !isSnowflake(i.channel_id)) {
      return { name, outcome: "bad", response: reply(UNKNOWN) };
    }
    const why = modalValue(data.components, "why") ?? "";
    const answer = await submitReport(
      {
        reporter,
        about: "Open the link to see whose message it is",
        where: `<https://discord.com/channels/${i.guild_id}/${i.channel_id}/${parsed.messageId}>\nThe link is the evidence. The message id comes from the reporter's app, so open the link to check it.`,
        why: reasonText(why, MAX_MODAL_REASON),
      },
      env,
      deps.now(),
    );
    return {
      name,
      outcome: answer.content.startsWith("Thank you") ? "ok" : "failed",
      response: reply(answer),
    };
  }

  async function readBounded(request: Request): Promise<Uint8Array<ArrayBuffer> | null> {
    const declared = Number(request.headers.get("content-length") ?? "0");
    if (declared > MAX_BODY_BYTES) return null;
    const reader = request.body?.getReader();
    if (!reader) return new Uint8Array(0);
    const chunks: Uint8Array[] = [];
    let total = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_BODY_BYTES) {
        await reader.cancel();
        return null;
      }
      chunks.push(value);
    }
    const all = new Uint8Array(total);
    let at = 0;
    for (const c of chunks) {
      all.set(c, at);
      at += c.byteLength;
    }
    return all;
  }

  return {
    async fetch(request: Request, env: Env, _ctx?: ExecutionContextLike): Promise<Response> {
      const started = deps.now();
      const url = new URL(request.url);
      if (request.method === "GET" && url.pathname === "/healthz") return text("ok", 200);
      if (request.method !== "POST" || url.pathname !== "/interactions") return text("Not found", 404);

      const key = env.DISCORD_PUBLIC_KEY ?? "";
      if (!isValidPublicKey(key) || env.PROJECT !== content.project.slug) {
        console.log(JSON.stringify({ event: "misconfigured" }));
        return text("Not configured", 500);
      }

      const signature = request.headers.get("x-signature-ed25519");
      const timestamp = request.headers.get("x-signature-timestamp");
      if (!signature || !timestamp || !/^[0-9]{1,12}$/.test(timestamp)) return text("Unauthorized", 401);
      const age = Math.abs(Math.floor(deps.now() / 1000) - Number(timestamp));
      if (age > MAX_TIMESTAMP_SKEW_SECONDS) return text("Unauthorized", 401);

      const body = await readBounded(request);
      if (body === null) return text("Payload too large", 413);
      if (!(await verifySignature(key, signature, timestamp, body))) return text("Unauthorized", 401);

      // from here the request is known to come from Discord.
      let parsed: unknown;
      try {
        parsed = JSON.parse(new TextDecoder().decode(body));
      } catch {
        return text("Bad request", 400);
      }
      if (!isRecord(parsed)) return text("Bad request", 400);
      if (parsed.type === TYPE_PING) return jsonResponse({ type: 1 });

      try {
        let result: { name: string; outcome: string; response: Response };
        if (parsed.type === TYPE_COMMAND) result = await handleCommand(parsed, env);
        else if (parsed.type === TYPE_MODAL_SUBMIT) result = await handleModal(parsed, env);
        else result = { name: "unknown", outcome: "unsupported", response: reply(UNKNOWN) };
        log(result.name, result.outcome, started, deps.now);
        return result.response;
      } catch {
        log("unknown", "error", started, deps.now);
        return reply(FAILED);
      }
    },
  };
}
