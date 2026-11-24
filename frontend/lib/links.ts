// the one place a link between the public site and the dashboard is made. The two public env values say where each half
// lives. Both unset or equal, means one address: every link is a plain path. Different values mean "split mode": a link
// that crosses between the halves is an absolute address.
import { appPathOf, linkTo, parseSplitConfig } from './publicPaths';

// read on the server at run time and inlined into the browser bundle at build time
export const SPLIT = parseSplitConfig(process.env.NEXT_PUBLIC_SITE_URL, process.env.NEXT_PUBLIC_APP_URL);

export const isSplit = SPLIT.split;

// the public site's address for a path
export function siteHref(path: string): string {
  return linkTo('site', path, SPLIT);
}

// the dashboard's address for a path
export function appHref(path: string): string {
  return linkTo('app', path, SPLIT);
}

// a dashboard path for use inside the dashboard: "/" for the overview in split mode
export function appPath(path: string): string {
  return appPathOf(path, SPLIT);
}

// true for the overview on either address
export function isOverviewPath(pathname: string): boolean {
  return pathname === '/dashboard' || (SPLIT.split && pathname === '/');
}

// what the site's main button says and where it goes. The sign-in cookie lives on the dashboard's address only, so with
// two addresses the site cannot know whether a visitor is signed in: the button always reads Dashboard and the dashboard
// sends a signed-out visitor to sign in. With one address it reads the cookie as before.
export function dashboardCta(signedIn: boolean): { href: string; label: string } {
  if (SPLIT.split) return { href: appHref('/dashboard'), label: 'Dashboard' };
  return signedIn ? { href: '/dashboard', label: 'Open dashboard' } : { href: '/login', label: 'Sign in' };
}

// the full public address of a site page, for places that print it (a link on paper has no address bar). The configured site
// address when there is one and the production address otherwise.
export function siteAbsolute(path: string): string {
  const origin = SPLIT.split ? SPLIT.siteOrigin : (process.env.NEXT_PUBLIC_SITE_URL || 'https://phaemos.com').replace(/\/+$/, '');
  return `${origin}${path.startsWith('/') ? path : `/${path}`}`;
}
