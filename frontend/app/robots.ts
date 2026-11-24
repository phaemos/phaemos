import { headers } from 'next/headers';
import type { MetadataRoute } from 'next';
import { hostKind } from '@/lib/publicPaths';
import { SPLIT } from '@/lib/links';

// what a crawler is told depends on which address asked. The dashboard's address disallows everything and names no
// sitemap. The site's address (and the one address of a single deployment) lists the signed-in routes as off limits
// and points at the sitemap. The Host header is the only thing read.
export default async function robots(): Promise<MetadataRoute.Robots> {
  const host = (await headers()).get('host');
  if (hostKind(host, SPLIT) === 'app') {
    return { rules: { userAgent: '*', disallow: '/' } };
  }
  const origin = SPLIT.split ? SPLIT.siteOrigin : (process.env.NEXT_PUBLIC_SITE_URL || 'https://phaemos.com').replace(/\/+$/, '');
  return {
    rules: [{ userAgent: '*', allow: '/', disallow: ['/api/', '/login', '/accept-invite', '/reset-password', '/dashboard', '/devices', '/alerts', '/tickets', '/compare', '/admin', '/profile'] }],
    sitemap: `${origin}/sitemap.xml`,
  };
}
