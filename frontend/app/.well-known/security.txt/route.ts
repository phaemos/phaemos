import { SPLIT } from '@/lib/links';

// security.txt as RFC 9116 asks for it, served from a route and not from a fixed file so that Expires is always a real
// date and Canonical names only the addresses that really serve this file. It is built once at build time, so Expires is
// 330 days after the build: a site that is never rebuilt lets it run out, which is the honest signal.
export const dynamic = 'force-static';

const DAYS = 330;

export function GET(): Response {
  const site = SPLIT.split ? SPLIT.siteOrigin : (process.env.NEXT_PUBLIC_SITE_URL || 'https://phaemos.com').replace(/\/+$/, '');
  // both addresses are this one deployment, so both serve the file. The API and the documentation site do not.
  const origins = SPLIT.split ? [SPLIT.siteOrigin, SPLIT.appOrigin] : [site];
  const expires = new Date(Date.now() + DAYS * 24 * 60 * 60 * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z');
  const body = [
    '# Security contact for PHAEMOS, in the format of RFC 9116.',
    'Contact: https://github.com/phaemos/phaemos/security/advisories/new',
    'Contact: mailto:security@phaemos.com',
    `Expires: ${expires}`,
    'Preferred-Languages: en',
    ...origins.map((o) => `Canonical: ${o}/.well-known/security.txt`),
    `Policy: ${site}/security`,
    '',
  ].join('\n');
  return new Response(body, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
}
