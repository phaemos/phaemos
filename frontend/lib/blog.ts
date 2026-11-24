// the blog's single description of a post: how its front matter is read and how its body is prepared. No file
// access lives here so the tests can feed it text. lib/blogSource.ts reads content/blog.

export interface PostMeta {
  slug: string;
  title: string;
  // an ISO day, 2026-05-01
  date: string;
  excerpt: string;
}

export interface Post extends PostMeta {
  body: string;
}

const FRONT_MATTER = /^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/;
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;
// a slug becomes part of an address and a file name, so only lower-case letters, digits and single hyphens pass
export const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

// reads a post file. The slug is the file name and never a field, so two files cannot claim one address. A file
// with no title, no valid date or a name that is not a plain slug is not a post: null makes the caller skip it or answer 404. Nothing renders an
// empty heading or "Invalid Date".
export function parsePost(slug: string, raw: string): Post | null {
  if (!SLUG.test(slug)) return null;
  const match = raw.match(FRONT_MATTER);
  if (!match) return null;
  const fields: Record<string, string> = {};
  for (const line of match[1].split(/\r?\n/)) {
    const sep = line.indexOf(':');
    if (sep === -1) continue;
    fields[line.slice(0, sep).trim()] = line.slice(sep + 1).trim().replace(/^"|"$/g, '');
  }
  const { title, date, excerpt = '' } = fields;
  if (!title || !date || !ISO_DAY.test(date) || Number.isNaN(new Date(date).getTime())) return null;
  return { slug, title, date, excerpt, body: stripTitleHeading(match[2].trim(), title) };
}

// the page prints the title as its one h1, so a first line "# <the same title>" in the file is dropped. Any other
// first line stays.
export function stripTitleHeading(body: string, title: string): string {
  const lines = body.split(/\r?\n/);
  const first = lines[0]?.match(/^#\s+(.*?)\s*#*\s*$/);
  if (!first || first[1].trim() !== title.trim()) return body;
  return lines.slice(1).join('\n').trim();
}

// newest first
export function sortPosts<T extends { date: string }>(posts: T[]): T[] {
  return [...posts].sort((a, b) => b.date.localeCompare(a.date));
}
