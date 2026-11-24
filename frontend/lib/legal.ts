// how a legal page is read: its front matter, the passages that depend on an optional service, the placeholders that
// the owner has still to fill and the contents list. No file access lives here so the tests can feed it text.
// lib/legalSource.ts reads content/legal.

export interface LegalMeta {
  title: string;
  description: string;
  // an ISO day once the page is published. The placeholder text until then
  version: string;
  // "Version date" or "Prepared on"
  versionLabel: string;
}

export interface LegalDoc extends LegalMeta {
  slug: string;
  body: string;
  toc: { id: string; text: string }[];
}

export type Services = Record<string, boolean>;

const FRONT_MATTER = /^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/;
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

// every placeholder is words in square brackets that are not followed by a bracket, because a link is [text](address). Any
// such pair counts, whatever its case or punctuation ("[ADDRESS LINE 2]", "[Company name]", "[NAME & ADDRESS]", "[X]"), so a
// placeholder cannot slip past the check by looking different. The marked words say what is missing.
export const PLACEHOLDER = /\[([^\][\n]+)\](?!\()/g;

// a real calendar day: the pattern holds and the day survives a round trip, so "2026-02-31" (which Date would read as 3 March) fails
export function isIsoDay(value: string): boolean {
  if (!ISO_DAY.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

// "a", "not a", "a|b" (any of) and "not a|b" (none of). An unknown key is an error, so a typo in a Markdown file fails
// the tests and the build and never quietly hides or shows a passage.
export function evaluate(expression: string, services: Services): boolean {
  let expr = expression.trim();
  let negate = false;
  if (/^not\s+/.test(expr)) {
    negate = true;
    expr = expr.replace(/^not\s+/, '');
  }
  const keys = expr.split('|').map((k) => k.trim());
  for (const key of keys) {
    if (!(key in services)) throw new Error(`unknown service "${key}" in "${expression}"`);
  }
  const any = keys.some((k) => services[k]);
  return negate ? !any : any;
}

// words that depend on the installation. {site} and {app} are the two addresses (the same one when the site and the dashboard
// share an address), {api} is the API's address and {providers} and {transferrers} are lists built from the services that are
// switched on, so a notice never names one that is off. They are replaced before the conditions are read.
export interface LegalVars {
  site: string;
  app: string;
  api: string;
}

export const DEFAULT_VARS: LegalVars = { site: 'phaemos.com', app: 'dashboard.phaemos.com', api: 'api.phaemos.com' };

// "A", "A or B", "A, B or C". There is no comma before the last word.
export function joinWords(words: string[], conjunction = 'or'): string {
  if (words.length <= 1) return words.join('');
  return `${words.slice(0, -1).join(', ')} ${conjunction} ${words[words.length - 1]}`;
}

export function tokensFor(services: Services, vars: LegalVars = DEFAULT_VARS): Record<string, string> {
  const on = (k: string) => Boolean(services[k]);
  const providers = [on('google') && 'Google', on('github') && 'GitHub', on('microsoft') && 'Microsoft'].filter(Boolean) as string[];
  // the services that carry the UK-US data bridge claim: the site host and the code host always, the API host and the bot check once the
  // hosted service is open, then each optional one that is on
  const transferrers = [on('hosted') && 'DigitalOcean', 'Vercel', on('hosted') && 'Cloudflare', (on('analytics') || on('google')) && 'Google', 'GitHub', on('microsoft') && 'Microsoft'].filter(Boolean) as string[];
  return {
    site: vars.site,
    app: vars.app,
    api: vars.api,
    providers: joinWords(providers),
    // the providers a password account can link (Microsoft cannot be linked)
    linkable: joinWords(providers.filter((p) => p !== 'Microsoft')),
    providers_and: joinWords(providers, 'and'),
    transferrers: joinWords(transferrers, 'and'),
  };
}

function fillTokens(text: string, services: Services, vars: LegalVars): string {
  const tokens = tokensFor(services, vars);
  return text.replace(/\{(site|app|api|providers|providers_and|linkable|transferrers)\}/g, (_m, key: string) => tokens[key]);
}

// an indented marker still counts: leaving it as visible text would print ":::if" on the page
const BLOCK_OPEN = /^\s*:::if\s+(.+?)\s*$/;
const BLOCK_CLOSE = /^\s*:::\s*$/;
const LINE_SUFFIX = /\s*\{if\s+([^}:]+)\}\s*$/;
const INLINE = /\{if\s+([^}:]+):([^}]*)\}/g;

// removes the passages for services that are off and the markers for the ones that are on
export function applyConditions(text: string, services: Services, vars: LegalVars = DEFAULT_VARS): string {
  const out: string[] = [];
  const stack: boolean[] = [];
  for (const line of fillTokens(text, services, vars).split(/\r?\n/)) {
    const open = line.match(BLOCK_OPEN);
    if (open) {
      stack.push(evaluate(open[1], services));
      continue;
    }
    if (BLOCK_CLOSE.test(line)) {
      if (stack.length === 0) throw new Error('a ::: line closes a block that was never opened');
      stack.pop();
      continue;
    }
    if (!stack.every(Boolean)) continue;
    const suffix = line.match(LINE_SUFFIX);
    if (suffix) {
      if (!evaluate(suffix[1], services)) continue;
      // a line that ends in a marker may also hold inline passages
      out.push(line.replace(LINE_SUFFIX, '').replace(INLINE, (_m, expr: string, words: string) => (evaluate(expr, services) ? words : '')));
      continue;
    }
    out.push(line.replace(INLINE, (_m, expr: string, words: string) => (evaluate(expr, services) ? words : '')));
  }
  if (stack.length > 0) throw new Error('a :::if block is never closed');
  return out.join('\n');
}

export interface PlaceholderHit {
  name: string;
  line: number;
  // false when the passage holding it is hidden by a service that is off
  active: boolean;
}

// every placeholder in a file with its line number (the line in the file, front matter included). A placeholder in a
// passage that is switched off does not count against publication, so it is reported as inactive.
export function scanPlaceholders(raw: string, services: Services, vars: LegalVars = DEFAULT_VARS): PlaceholderHit[] {
  const hits: PlaceholderHit[] = [];
  const stack: boolean[] = [];
  fillTokens(raw, services, vars).split(/\r?\n/).forEach((line, i) => {
    const open = line.match(BLOCK_OPEN);
    if (open) {
      stack.push(evaluate(open[1], services));
      return;
    }
    if (BLOCK_CLOSE.test(line)) {
      stack.pop();
      return;
    }
    let active = stack.every(Boolean);
    const suffix = line.match(LINE_SUFFIX);
    if (suffix && !evaluate(suffix[1], services)) active = false;
    // inline passages are cut out before looking
    const visible = line.replace(INLINE, (_m, expr: string, words: string) => (evaluate(expr, services) ? words : ''));
    for (const m of visible.matchAll(PLACEHOLDER)) hits.push({ name: m[1], line: i + 1, active });
  });
  return hits;
}

// a heading's text with the markers a reader never sees taken out and its anchor
export function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-');
}

// the contents list: every h2, outside code fences
export function headings(body: string): { id: string; text: string }[] {
  const out: { id: string; text: string }[] = [];
  let fenced = false;
  for (const line of body.split(/\r?\n/)) {
    if (/^```/.test(line)) fenced = !fenced;
    if (fenced) continue;
    const m = line.match(/^##\s+(.+?)\s*#*\s*$/);
    if (m) out.push({ id: slugify(m[1]), text: m[1] });
  }
  return out;
}

// reads a legal file. A file with no title, description or version is not a page: null makes the caller answer 404.
export function parseLegal(slug: string, raw: string, services: Services, vars: LegalVars = DEFAULT_VARS): LegalDoc | null {
  const match = raw.match(FRONT_MATTER);
  if (!match) return null;
  const fields: Record<string, string> = {};
  for (const line of match[1].split(/\r?\n/)) {
    const sep = line.indexOf(':');
    if (sep === -1) continue;
    fields[line.slice(0, sep).trim()] = line.slice(sep + 1).trim().replace(/^"|"$/g, '');
  }
  const { title, description, version, versionLabel = 'Version date' } = fields;
  if (!title || !description || !version) return null;
  const body = applyConditions(match[2], services, vars).trim();
  return { slug, title, description, version, versionLabel, body, toc: headings(body) };
}

// a body split into prose and tables. A table is a run of lines that start with a pipe: the first line holds the
// column names, the second the dashes and the rest the rows. The prose goes through the Markdown renderer and a table
// is drawn as a real table, because the renderer has no table support.
export type Block = { kind: 'prose'; text: string } | { kind: 'table'; head: string[]; rows: string[][] };

function cells(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    // a pipe inside `code` is part of the code. \| is a literal pipe
    .split(/(?<!\\)\|(?=(?:[^`]*`[^`]*`)*[^`]*$)/)
    .map((c) => c.trim().replace(/\\\|/g, '|'));
}

export function splitBlocks(body: string): Block[] {
  const blocks: Block[] = [];
  let prose: string[] = [];
  const lines = body.split(/\r?\n/);
  const flush = () => {
    const text = prose.join('\n').trim();
    if (text) blocks.push({ kind: 'prose', text });
    prose = [];
  };
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trimStart().startsWith('|') && i + 1 < lines.length && /^\s*\|[\s|:-]+\|\s*$/.test(lines[i + 1])) {
      flush();
      const head = cells(lines[i]);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].trimStart().startsWith('|')) {
        rows.push(cells(lines[i]));
        i++;
      }
      i--;
      blocks.push({ kind: 'table', head, rows });
    } else {
      prose.push(lines[i]);
    }
  }
  flush();
  return blocks;
}

// a placeholder becomes a link to #placeholder with its name as the title, so the renderer can mark it in the page
// and nobody mistakes a draft for a finished page. The raw bracket never reaches the screen.
export function markPlaceholders(text: string): string {
  return text.replace(PLACEHOLDER, (_m, name: string) => `[to be completed before publication](#placeholder "${name.toLowerCase().replace(/"/g, "'")}")`);
}

// true while the page still shows "to be completed before publication": a placeholder in its text or a version that is not a real day
export function isDraft(doc: LegalDoc): boolean {
  return !isIsoDay(doc.version) || new RegExp(PLACEHOLDER.source).test(doc.body);
}

// the version field of a page that is not a real day and not already a bracketed placeholder ("22 November 2026", "TBC", "2026-02-31");
// the page shows "to be completed before publication" for it, so the build check must count it. Returns its line or null.
export function badVersionLine(raw: string): number | null {
  const lines = raw.split(/\r?\n/);
  if (lines[0]?.trim() !== '---') return null;
  for (let i = 1; i < lines.length && lines[i].trim() !== '---'; i++) {
    const m = lines[i].match(/^version:\s*(.*)$/);
    if (!m) continue;
    const value = m[1].trim().replace(/^"|"$/g, '');
    return isIsoDay(value) || new RegExp(PLACEHOLDER.source).test(value) ? null : i + 1;
  }
  return null;
}
