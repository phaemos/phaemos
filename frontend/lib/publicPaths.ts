// the public site pages: every address a signed-out visitor may open that belongs to the website. proxy.ts lets these
// through and the analytics scope below counts only these. The sign-in and invitation pages are public too but are not
// site pages: an invitation address carries a token, so neither is ever counted.
export const SITE_PATHS = [
  '/status',
  '/about',
  '/blog',
  '/changelog',
  '/docs',
  '/privacy',
  '/cookies',
  '/terms',
  '/security',
  '/accessibility',
  '/faq',
  '/support',
  '/contact',
];

// reachable without signing in but not part of the website. The .well-known folder holds security.txt.
export const OTHER_PUBLIC_PATHS = ['/login', '/accept-invite', '/reset-password', '/favicon.ico', '/.well-known'];

export function isSitePath(pathname: string): boolean {
  return pathname === '/' || SITE_PATHS.some((p) => pathname === p || pathname.startsWith(p + '/'));
}

// the shape of what Vercel Web Analytics hands to beforeSend: a page view or a custom event with the page's address
export interface AnalyticsEvent {
  type: string;
  url: string;
}

// Vercel Web Analytics may record the page address and its query string. Dashboard addresses carry machine ids and an
// invitation address carries a token, so only the public site pages are counted. Returning null drops the event. A
// counted address loses its query string and fragment. appHost is the dashboard's host when the two halves are on
// different addresses.
export function scopeAnalytics<T extends AnalyticsEvent>(event: T, appHost?: string): T | null {
  let url: URL;
  try {
    url = new URL(event.url, 'https://placeholder.invalid');
  } catch {
    return null;
  }
  // with two addresses the dashboard's root is the overview, which is not a site page, so nothing on its address counts
  if (appHost && normaliseHost(url.host) === appHost) return null;
  if (!isSitePath(url.pathname)) return null;
  return { ...event, url: event.url.startsWith('http') ? `${url.origin}${url.pathname}` : url.pathname };
}

// ---- two addresses ----------------------------------------------------------------------------------------------
// the public site can live at one address and the dashboard at another, served by this one deployment. Both addresses
// are public env values. When they are equal or the dashboard one is unset or unreadable, nothing changes: every page
// answers on the one address. When they differ the proxy sends each request to the address that owns the page.

// the pages behind sign-in plus the sign-in and invitation pages: the dashboard's half of the site
export const APP_PATHS = ['/dashboard', '/devices', '/alerts', '/tickets', '/compare', '/models', '/admin', '/profile', '/login', '/accept-invite', '/reset-password'];

export interface SplitConfig {
  split: boolean;
  siteOrigin: string;
  appOrigin: string;
  siteHost: string;
  appHost: string;
}

const SINGLE: SplitConfig = { split: false, siteOrigin: '', appOrigin: '', siteHost: '', appHost: '' };

// "dashboard.phaemos.com", "DASHBOARD.phaemos.com:443" and "localhost:3200" all compare in one lower-case form with the default port dropped
export function normaliseHost(host: string): string {
  // the port comes off first so that a dot before it ("app.example.test.:3210") goes too
  return host.trim().toLowerCase().replace(/:(80|443)$/, '').replace(/\.(?=:\d+$|$)/, '');
}

function readUrl(value: string | undefined): URL | null {
  if (!value || !value.trim()) return null;
  try {
    const url = new URL(value.trim());
    return url.protocol === 'http:' || url.protocol === 'https:' ? url : null;
  } catch {
    return null;
  }
}

export function parseSplitConfig(siteUrl?: string, appUrl?: string): SplitConfig {
  const site = readUrl(siteUrl);
  const app = readUrl(appUrl);
  if (!site || !app) return SINGLE;
  const siteHost = normaliseHost(site.host);
  const appHost = normaliseHost(app.host);
  if (siteHost === appHost) return SINGLE;
  return { split: true, siteOrigin: site.origin, appOrigin: app.origin, siteHost, appHost };
}

export type HostKind = 'site' | 'app' | 'other';

// the Host header is the only thing compared. www on the site address counts as the site. Any other host (a preview
// address, localhost, an address someone typed) is "other" and is never redirected.
export function hostKind(host: string | null | undefined, config: SplitConfig): HostKind {
  if (!config.split || !host) return 'other';
  const h = normaliseHost(host);
  if (h === config.appHost) return 'app';
  if (h === config.siteHost || h === `www.${config.siteHost}`) return 'site';
  return 'other';
}

export type Decision =
  | { type: 'pass' }
  | { type: 'redirect'; url: string; permanent?: true }
  | { type: 'rewrite'; pathname: string }
  | { type: 'notfound' };

const STATIC_FILE_PATTERN = /\.(?:png|jpe?g|gif|webp|avif|svg|ico|txt|xml|webmanifest|json|woff2?|mp4|webm)$/i;

// never redirected, on either address: the framework's own files, Vercel's, the well-known folder, the API proxy path,
// the two crawler files and every static file
function isNeutral(path: string): boolean {
  return (
    path.startsWith('/_next/') ||
    path.startsWith('/_vercel/') ||
    path === '/.well-known' ||
    path.startsWith('/.well-known/') ||
    path.startsWith('/api/') ||
    path === '/robots.txt' ||
    path === '/sitemap.xml' ||
    // a real file lives at the root or in a public folder. A dashboard page that happens to end in ".png" is not one.
    (STATIC_FILE_PATTERN.test(path) && !isAppPath(path))
  );
}

// one slash at the front and none at the back. A path that begins with two slashes would read as another host once
// it follows an origin, so the run of slashes is collapsed. The path and query are the only request data a redirect uses.
export function cleanPath(pathname: string): string {
  const collapsed = ('/' + pathname.replace(/^\/+/, '')).replace(/\/{2,}/g, '/');
  return collapsed.length > 1 ? collapsed.replace(/\/+$/, '') : collapsed;
}

const under = (list: string[], path: string) => list.some((p) => path === p || path.startsWith(p + '/'));
const isAppPath = (path: string) => under(APP_PATHS, path);
const isSitePage = (path: string) => path !== '/' && under(SITE_PATHS, path);

function withQuery(search: string): string {
  return search && search !== '?' ? (search.startsWith('?') ? search : `?${search}`) : '';
}

// which address owns this request and what to do about it. Pure: the host, the path and the query go in.
export function routeRequest(input: { host: string | null | undefined; pathname: string; search?: string }, config: SplitConfig): Decision {
  if (!config.split) return { type: 'pass' };
  const kind = hostKind(input.host, config);
  if (kind === 'other') return { type: 'pass' };
  const path = cleanPath(input.pathname);
  const query = withQuery(input.search ?? '');

  if (kind === 'app' && path === '/sitemap.xml') return { type: 'notfound' };
  if (isNeutral(path)) return { type: 'pass' };

  if (kind === 'app') {
    if (path === '/') return { type: 'rewrite', pathname: '/dashboard' };
    if (path === '/dashboard') return { type: 'redirect', url: `${config.appOrigin}/${query}` };
    if (isSitePage(path)) return { type: 'redirect', url: `${config.siteOrigin}${path}${query}` };
    return { type: 'pass' };
  }

  // the site address. The www form of it moves to the plain one. That move is permanent. The site address itself may
  // be a www host, so "starts with www." is not the test: "is not the configured host" is.
  const isWww = normaliseHost(input.host ?? '') !== config.siteHost;
  if (isAppPath(path)) return { type: 'redirect', url: `${config.appOrigin}${path === '/dashboard' ? '/' : path}${query}` };
  if (isWww) return { type: 'redirect', url: `${config.siteOrigin}${path === '/' ? '' : path}${query}` || config.siteOrigin, permanent: true };
  return { type: 'pass' };
}

// the address of a page on the site or on the dashboard, for a link that may cross between them. Absolute when the two
// halves are on different addresses and relative otherwise. The overview is "/" on the dashboard address.
export function linkTo(target: 'site' | 'app', path: string, config: SplitConfig): string {
  const clean = path.startsWith('/') ? path : `/${path}`;
  if (!config.split) return clean;
  if (target === 'site') return `${config.siteOrigin}${clean === '/' ? '' : clean}` || config.siteOrigin;
  const inApp = clean === '/dashboard' ? '/' : clean.replace(/^\/dashboard(?=[?#])/, '/');
  return `${config.appOrigin}${inApp}`;
}

// the path of a dashboard page on the dashboard's own address, for links inside the dashboard: "/" for the overview when split
export function appPathOf(path: string, config: SplitConfig): string {
  if (!config.split) return path;
  return path === '/dashboard' ? '/' : path;
}

// ---- the page someone asked for before signing in --------------------------------------------------------------------
// a signed-out visit to a dashboard page goes to sign-in with the page it wanted in `next`. Only a path that belongs to the
// dashboard is accepted and it is used as a path on this address, never as a place to go. It cannot lead anywhere else.
export function safeNextPath(value: string | null | undefined): string | null {
  if (!value || value.length > 512) return null;
  // one slash and then a letter or digit: nothing that could read as another host ("//", "/\") and no control characters
  if (!/^\/[A-Za-z0-9._~%!$&'()*+,;=:@/?#-]*$/.test(value) || value.startsWith('//') || value.includes('\\')) return null;
  let path: string;
  try {
    path = new URL(value, 'https://placeholder.invalid').pathname;
  } catch {
    return null;
  }
  if (path.includes('//') || path.split('/').some((seg) => seg === '..' || seg === '.')) return null;
  if (['/login', '/accept-invite', '/reset-password'].some((p) => path === p || path.startsWith(`${p}/`))) return null;
  return isAppPath(path) ? value : null;
}

// the `next` value for a page a signed-out visitor asked for: the path and query. Null for the overview and for anything
// that is not a dashboard page
export function nextFor(pathname: string, search = ''): string | null {
  const path = cleanPath(pathname);
  if (path === '/' || path === '/dashboard') return null;
  return safeNextPath(`${path}${withQuery(search)}`);
}

// the pages that get the strict, nonce-based script policy: the dashboard, the sign-in page and the invitation page. With two
// addresses "/" on the dashboard's address is the overview and so is private as well.
export function isPrivateSurface(pathname: string, kind: HostKind, config: SplitConfig): boolean {
  const path = cleanPath(pathname);
  if (config.split && kind === 'app' && path === '/') return true;
  return isAppPath(path);
}
