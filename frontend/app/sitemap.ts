import type { MetadataRoute } from 'next';
import { hasItems, versionHref } from '@/lib/changelog';
import { loadPosts } from '@/lib/blogSource';
import { loadReleases } from '@/lib/changelogSource';
import { SPLIT } from '@/lib/links';
import { legalIsPublished, type LegalSlug } from '@/lib/legalSource';

// absolute addresses use the public site's address, never the dashboard's
const BASE_URL = SPLIT.split ? SPLIT.siteOrigin : (process.env.NEXT_PUBLIC_SITE_URL || 'https://phaemos.com').replace(/\/+$/, '');

// only public pages belong here. Signed-in routes are behind a login, so a crawler could not read them anyway.
const PAGES: { path: string; priority: number; changeFrequency: 'weekly' | 'monthly' | 'yearly' }[] = [
  { path: '', priority: 1, changeFrequency: 'monthly' },
  { path: '/about', priority: 0.7, changeFrequency: 'monthly' },
  { path: '/docs', priority: 0.8, changeFrequency: 'monthly' },
  { path: '/blog', priority: 0.6, changeFrequency: 'monthly' },
  { path: '/changelog', priority: 0.7, changeFrequency: 'weekly' },
  { path: '/faq', priority: 0.6, changeFrequency: 'monthly' },
  { path: '/support', priority: 0.5, changeFrequency: 'monthly' },
  { path: '/contact', priority: 0.4, changeFrequency: 'yearly' },
  { path: '/status', priority: 0.4, changeFrequency: 'weekly' },
];

// the legal pages are listed only once they are finished. A page with an open placeholder is a draft: it is noindex and
// stays out of this list.
const LEGAL: { slug: LegalSlug; priority: number }[] = [
  { slug: 'security', priority: 0.5 },
  { slug: 'accessibility', priority: 0.3 },
  { slug: 'privacy', priority: 0.3 },
  { slug: 'cookies', priority: 0.3 },
  { slug: 'terms', priority: 0.3 },
];

export default function sitemap(): MetadataRoute.Sitemap {
  const releases = loadReleases().filter((r) => !r.unreleased || hasItems(r));
  return [
    ...PAGES.map((p) => ({ url: `${BASE_URL}${p.path}`, changeFrequency: p.changeFrequency, priority: p.priority })),
    ...LEGAL.filter((l) => legalIsPublished(l.slug)).map((l) => ({ url: `${BASE_URL}/${l.slug}`, changeFrequency: 'yearly' as const, priority: l.priority })),
    ...loadPosts().map((p) => ({ url: `${BASE_URL}/blog/${encodeURIComponent(p.slug)}`, lastModified: new Date(p.date), changeFrequency: 'yearly' as const, priority: 0.5 })),
    ...releases.map((r) => ({
      url: `${BASE_URL}${versionHref(r)}`,
      lastModified: r.date ? new Date(r.date) : undefined,
      changeFrequency: 'yearly' as const,
      priority: 0.4,
    })),
  ];
}
