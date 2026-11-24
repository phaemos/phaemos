// the parts of Discord's interaction format that this worker reads and writes.
import { clip } from "./text.ts";

export const TYPE_PING = 1;
export const TYPE_COMMAND = 2;
export const TYPE_MODAL_SUBMIT = 5;

export const FLAG_SUPPRESS_EMBEDS = 4;
export const FLAG_EPHEMERAL = 64;
export const MANAGE_MESSAGES = 8192n;
export const MAX_CONTENT = 2000;

export type Json = Record<string, unknown>;

export interface Answer {
  content: string;
  ephemeral: boolean;
}

// ids from Discord are digit strings. the shape is checked before one is used anywhere.
const SNOWFLAKE = /^[0-9]{17,20}$/;
const TOKEN = /^[A-Za-z0-9_-]{16,512}$/;

export function isSnowflake(v: unknown): v is string {
  return typeof v === "string" && SNOWFLAKE.test(v);
}

export function isInteractionToken(v: unknown): v is string {
  return typeof v === "string" && TOKEN.test(v);
}

export function isRecord(v: unknown): v is Json {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

export function str(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}

export function messageBody(answer: Answer): Json {
  return {
    content: clip(answer.content, MAX_CONTENT),
    flags: FLAG_SUPPRESS_EMBEDS | (answer.ephemeral ? FLAG_EPHEMERAL : 0),
    allowed_mentions: { parse: [] },
  };
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

export function reply(answer: Answer): Response {
  return jsonResponse({ type: 4, data: messageBody(answer) });
}

// the ids of the staff roles, from a secret. a value that is set but holds no valid id means nobody.
export function parseStaffRoles(value: string | undefined): Set<string> | null {
  if (value === undefined || value.trim() === "") return null;
  return new Set(
    value
      .split(",")
      .map((v) => v.trim())
      .filter((v) => isSnowflake(v)),
  );
}

// staff are identified by role when the secret is set, because a moderator is denied Manage Messages in the
// log channel and the permission bit of the request is worked out for that channel. without the secret the
// bit is the fallback.
export function isStaffMember(member: Json | null, staffRoles: Set<string> | null): boolean {
  if (!member) return false;
  if (staffRoles === null) return isStaff(member.permissions);
  const roles = Array.isArray(member.roles) ? member.roles : [];
  return roles.some((r) => typeof r === "string" && staffRoles.has(r));
}

export function isStaff(permissions: unknown): boolean {
  if (typeof permissions !== "string" || !/^[0-9]{1,20}$/.test(permissions)) return false;
  return (BigInt(permissions) & MANAGE_MESSAGES) === MANAGE_MESSAGES;
}

// finds a named option in a command's data. a subcommand nests its options one level down.
export function findOption(data: Json, name: string): unknown {
  const options = Array.isArray(data.options) ? data.options : [];
  for (const o of options) {
    if (!isRecord(o)) continue;
    if (o.name === name) return o.value;
    if (Array.isArray(o.options)) {
      for (const inner of o.options) {
        if (isRecord(inner) && inner.name === name) return inner.value;
      }
    }
  }
  return undefined;
}

export function subcommandName(data: Json): string | undefined {
  const options = Array.isArray(data.options) ? data.options : [];
  const first = options[0];
  return isRecord(first) && first.type === 1 ? str(first.name) : undefined;
}
