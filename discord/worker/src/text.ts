// helpers that make outside text safe to place in an answer.

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

// control characters and invisible direction marks can hide or reorder text, so they never pass.
function isHidden(code: number): boolean {
  return (
    (code <= 0x1f && code !== 0x0a) ||
    (code >= 0x7f && code <= 0x9f) ||
    (code >= 0x200b && code <= 0x200f) ||
    (code >= 0x2028 && code <= 0x202e) ||
    (code >= 0x2060 && code <= 0x2069) ||
    code === 0xfeff
  );
}

export function plain(input: string): string {
  let out = "";
  for (const ch of input.replace(/\r\n?/g, "\n")) {
    const code = ch.codePointAt(0) ?? 0;
    if (!isHidden(code)) out += ch;
  }
  return out;
}

// the characters Discord reads as markup or as a mention or channel link.
export function escapeMarkdown(input: string): string {
  return plain(input)
    .replace(/[\\`*_~|<>#[\]()]/g, "\\$&")
    .replace(/^(\s*)([-+])/gm, "$1\\$2");
}

export function oneLine(input: string): string {
  return plain(input).replace(/\s+/g, " ").trim();
}

// cut by whole characters and say so with three dots.
export function clip(input: string, max: number): string {
  const chars = Array.from(input);
  if (chars.length <= max) return input;
  return `${chars.slice(0, Math.max(0, max - 3)).join("")}...`;
}

// cut escaped text without leaving a lone backslash at the end.
export function clipEscaped(input: string, max: number): string {
  let out = clip(input, max);
  const body = out.endsWith("...") && out !== input ? out.slice(0, -3) : null;
  if (body !== null) {
    let slashes = 0;
    for (let i = body.length - 1; i >= 0 && body[i] === "\\"; i--) slashes++;
    if (slashes % 2 === 1) out = `${body.slice(0, -1)}...`;
  }
  return out;
}

export function formatDate(iso: unknown): string | null {
  if (typeof iso !== "string") return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

export function formatTime(ms: number): string {
  const d = new Date(ms);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${hh}:${mm} UTC`;
}

const COMMENT = /<!--[\s\S]*?-->/g;
// an HTML comment or any tag, in one pattern so a single pass removes both
const MARKUP = /<!--[\s\S]*?-->|<[^>]*>/g;

// taking one comment or tag out can join the text on either side into a new one (as in <scr<b></b>ipt>),
// so the pass repeats until nothing changes
function removeAll(text: string, pattern: RegExp): string {
  let out = text;
  let before: string;
  do {
    before = out;
    out = out.replace(pattern, "");
  } while (out !== before);
  return out;
}

// release notes arrive as markdown. keep the words and drop the markup before they are quoted. Comments go
// first, so a link inside one is never shown. Tags go last, because unwrapping a link can put a "<" next
// to a ">" that were apart
export function notesToPlain(markdown: string): string {
  const words = removeAll(plain(markdown), COMMENT)
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "[Image: $1]")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/^\s{0,3}#{1,6}\s*/gm, "")
    .replace(/^\s*>\s?\[!(\w+)\]/gm, "$1:");
  return removeAll(words, MARKUP)
    .replace(/\n{2,}/g, "\n")
    .trim();
}
