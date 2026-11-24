import { readFileSync } from 'fs';
import { join } from 'path';
import { LEGAL_VARS, SERVICES } from '@/content/legal/services';
import type { Metadata } from 'next';
import { isDraft, parseLegal, type LegalDoc } from './legal';

const CONTENT_DIR = join(process.cwd(), 'content', 'legal');

// one legal page by name, with the passages for services that are off already removed. The owner and a solicitor edit
// the Markdown file and nothing else.
export type LegalSlug = 'privacy' | 'cookies' | 'terms' | 'security' | 'accessibility';

export function getLegalPage(slug: LegalSlug): LegalDoc | null {
  let raw: string;
  try {
    raw = readFileSync(join(CONTENT_DIR, `${slug}.md`), 'utf8');
  } catch {
    return null;
  }
  // a typo in a conditional marker throws here on purpose: a wrong passage must never be shown or hidden quietly
  return parseLegal(slug, raw, SERVICES, LEGAL_VARS);
}

// the page's metadata. A page that still has a placeholder or a version that is not a real date is a draft: it is kept out of
// search results (and out of the sitemap) until the owner has filled it in.
export function legalMetadata(slug: LegalSlug, fallbackTitle: string): Metadata {
  const doc = getLegalPage(slug);
  if (!doc) return { title: fallbackTitle };
  return { title: doc.title, description: doc.description, ...(isDraft(doc) ? { robots: { index: false, follow: false } } : {}) };
}

// true when the page is finished and may be listed in the sitemap
export function legalIsPublished(slug: LegalSlug): boolean {
  const doc = getLegalPage(slug);
  return Boolean(doc) && !isDraft(doc as LegalDoc);
}
