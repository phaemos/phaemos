// parses CHANGELOG.md (Keep a Changelog layout) into releases. It is a pure function so the page, the detail pages
// and the tests all share it. Nothing is dropped: every section keeps its raw Markdown in `body` while any text
// the parser does not recognise stays attached to the release or section it sat in.

export type SectionKind = 'security' | 'added' | 'changed' | 'fixed' | 'removed' | 'deprecated' | 'other';

export interface ChangelogSection {
  // the heading as written, for example "Added"
  name: string;
  kind: SectionKind;
  // each top-level list item as Markdown, without its bullet. Used for counts and summaries.
  items: string[];
  // the whole section as Markdown, kept so the detail page renders everything the file holds
  body: string;
}

export interface Release {
  // "2.5.0" or "Unreleased"
  version: string;
  // used in URLs: the version or "unreleased"
  slug: string;
  // the ISO date as written or null when the heading has none
  date: string | null;
  unreleased: boolean;
  sections: ChangelogSection[];
  // Markdown that sits under the release heading before its first section
  preamble: string;
}

export const SECTION_KINDS: readonly SectionKind[] = ['security', 'added', 'changed', 'fixed', 'removed', 'deprecated', 'other'];

// the order a summary looks for items in
const SUMMARY_ORDER: readonly SectionKind[] = ['security', 'added', 'changed', 'fixed', 'removed', 'deprecated'];

const RELEASE_HEADING = /^##\s+\[([^\]]+)\](?:\s+-\s+(\S+))?\s*$/;
const SECTION_HEADING = /^###\s+(.+?)\s*$/;
const TOP_BULLET = /^[-*+]\s+(.*)$/;
const RULE = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/;

export function kindOf(name: string): SectionKind {
  const n = name.trim().toLowerCase();
  return n !== 'other' && (SECTION_KINDS as readonly string[]).includes(n) ? (n as SectionKind) : 'other';
}

// strips the blank lines at both ends and the horizontal rules that only separate releases
function tidy(lines: string[]): string {
  const kept = lines.filter((l) => !RULE.test(l));
  while (kept.length && kept[0].trim() === '') kept.shift();
  while (kept.length && kept[kept.length - 1].trim() === '') kept.pop();
  return kept.join('\n');
}

// splits a section body into its top-level list items. A line that is not indented and not a bullet ends nothing:
// it continues the current item (a lazy continuation), which is how the file wraps long items.
function itemsOf(body: string): string[] {
  const items: string[] = [];
  let current: string[] | null = null;
  for (const line of body.split('\n')) {
    const m = TOP_BULLET.exec(line);
    if (m) {
      if (current) items.push(tidy(current));
      current = [m[1]];
    } else if (current) {
      current.push(line.replace(/^ {1,2}/, ''));
    }
  }
  if (current) items.push(tidy(current));
  return items.filter((i) => i !== '');
}

function makeSection(name: string, lines: string[]): ChangelogSection {
  const body = tidy(lines);
  return { name, kind: kindOf(name), items: itemsOf(body), body };
}

export function parseChangelog(source: string): Release[] {
  const releases: Release[] = [];
  let release: Release | null = null;
  let sectionName: string | null = null;
  let buffer: string[] = [];
  let inFence = false;

  const closeSection = () => {
    if (!release) return;
    if (sectionName === null) release.preamble = tidy(buffer);
    else release.sections.push(makeSection(sectionName, buffer));
    buffer = [];
  };

  for (const line of source.replace(/\r\n?/g, '\n').split('\n')) {
    if (/^\s*(```|~~~)/.test(line)) inFence = !inFence;
    const rel = inFence ? null : RELEASE_HEADING.exec(line);
    if (rel) {
      closeSection();
      const version = rel[1].trim();
      const unreleased = version.toLowerCase() === 'unreleased';
      release = { version, slug: unreleased ? 'unreleased' : version, date: rel[2] ?? null, unreleased, sections: [], preamble: '' };
      releases.push(release);
      sectionName = null;
      continue;
    }
    // the file's own title and intro sit above the first release and belong to no release
    if (!release) continue;
    const sec = inFence ? null : SECTION_HEADING.exec(line);
    if (sec) {
      closeSection();
      sectionName = sec[1];
      continue;
    }
    buffer.push(line);
  }
  closeSection();
  return releases;
}

// --- summaries -------------------------------------------------------------------------------------------------

// taking one tag out can join the text on either side into a new one (as in <scr<b></b>ipt>), so the pass
// repeats until nothing changes
function removeTags(text: string): string {
  let out = text;
  let before: string;
  do {
    before = out;
    out = out.replace(/<[^>]+>/g, '');
  } while (out !== before);
  return out;
}

// plain text from Markdown: links keep their text, code and emphasis lose their marks. Tags go before the code and
// emphasis marks as they always have. They go once more at the end, because unwrapping code or a link can put a "<"
// next to a ">" that were apart
export function stripMarkdown(md: string): string {
  const linksDone = md.replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/\[([^\]]+)\]\([^)]*\)/g, '$1');
  const unwrapped = removeTags(linksDone)
    .replace(/`([^`]*)`/g, '$1')
    .replace(/(\*\*|__)(.*?)\1/g, '$2')
    .replace(/(^|[\s(])[*_]([^*_\s][^*_]*?)[*_](?=[\s).,;:!?]|$)/g, '$1$2');
  return removeTags(unwrapped)
    .replace(/\s+/g, ' ')
    .trim();
}

const ABBREVIATIONS = /(?:e\.g|i\.e|etc|vs|approx|no)$/i;

// the first sentence of an item's opening paragraph. A nested list or a second paragraph is not part of it.
export function firstSentence(item: string): string {
  const paragraph: string[] = [];
  for (const line of item.split('\n')) {
    if (line.trim() === '' || /^\s*[-*+]\s/.test(line)) break;
    paragraph.push(line.trim());
  }
  const text = stripMarkdown(paragraph.join(' '));
  const end = /[.!?](?=\s|$)/g;
  let m: RegExpExecArray | null;
  while ((m = end.exec(text))) {
    if (ABBREVIATIONS.test(text.slice(0, m.index))) continue;
    return text.slice(0, m.index + 1);
  }
  return /[.!?]$/.test(text) ? text : `${text}.`;
}

// cuts at the last word boundary that fits, so a sentence is never broken inside a word
function cutAtWord(text: string, limit: number): string {
  if (text.length <= limit) return text;
  const cut = text.slice(0, limit + 1);
  const space = cut.lastIndexOf(' ');
  const head = (space > 0 ? cut.slice(0, space) : cut.slice(0, limit)).replace(/[\s,;:(-]+$/, '');
  return `${head}…`;
}

const SUMMARY_LIMIT = 180;

// the sentence written under the release heading when there is one. Otherwise the first sentence of up to the first two items of the most important section present. It falls back to the
// first sentence alone when two would pass the limit and cuts at a word only if even that is too long.
export function summarise(release: Release, preferred?: SectionKind): string {
  // a sentence written under the heading is the summary. A filter still wants its own section's wording.
  if (!preferred && release.preamble) return stripMarkdown(release.preamble);
  const order = preferred ? [preferred] : SUMMARY_ORDER;
  for (const kind of order) {
    const section = release.sections.find((s) => s.kind === kind && s.items.length > 0);
    if (!section) continue;
    const first = firstSentence(section.items[0]);
    if (section.items.length > 1) {
      const both = `${first} ${firstSentence(section.items[1])}`;
      if (both.length <= SUMMARY_LIMIT) return both;
    }
    return cutAtWord(first, SUMMARY_LIMIT);
  }
  return '';
}

// --- counts and filters ----------------------------------------------------------------------------------------

export type CountMap = Partial<Record<SectionKind, number>>;

// one count per kind. A section with text and no list items counts as one change so it is not invisible.
export function countByKind(release: Release): CountMap {
  const counts: CountMap = {};
  for (const s of release.sections) {
    const n = s.items.length || (s.body ? 1 : 0);
    if (n) counts[s.kind] = (counts[s.kind] ?? 0) + n;
  }
  return counts;
}

export const FILTERS = ['added', 'changed', 'fixed', 'security', 'removed'] as const;
export type FilterKind = (typeof FILTERS)[number];

export function isFilter(value: string): value is FilterKind {
  return (FILTERS as readonly string[]).includes(value);
}

export function hasKind(release: Release, kind: SectionKind): boolean {
  return (countByKind(release)[kind] ?? 0) > 0;
}

export function hasItems(release: Release): boolean {
  return release.sections.some((s) => s.items.length > 0 || s.body !== '') || release.preamble !== '';
}

export function versionHref(release: Release): string {
  return `/changelog/${encodeURIComponent(release.slug)}`;
}

export function findRelease(releases: Release[], slug: string): Release | undefined {
  return releases.find((r) => r.slug === slug);
}

export function releaseYear(release: Release): string | null {
  return release.date ? release.date.slice(0, 4) : null;
}

export function sectionTitle(kind: SectionKind): string {
  return kind.charAt(0).toUpperCase() + kind.slice(1);
}
