import { NextRequest, NextResponse } from 'next/server';
import { SIGNED_IN_COOKIE } from '@/lib/signedIn';
import { buildCsp, buildNonceCsp } from '@/lib/csp.mjs';
import { isUuid } from '@/lib/uuid';
import { themeScriptHash } from '@/lib/themeHash.mjs';
import { APP_PATHS, isPrivateSurface, OTHER_PUBLIC_PATHS, SITE_PATHS, hostKind, nextFor, parseSplitConfig, routeRequest } from '@/lib/publicPaths';

// the public site and the dashboard can answer on two addresses from this one deployment. The Host header is the only
// thing compared with the two configured addresses and a redirect is built from a configured origin plus the path and
// query, never from anything else in the request. See lib/publicPaths.ts. With one address this does nothing.
const SPLIT = parseSplitConfig(process.env.NEXT_PUBLIC_SITE_URL, process.env.NEXT_PUBLIC_APP_URL);

// the home page is public by exact match only: a prefix match on "/" would make every page public
const PUBLIC_EXACT = ['/'];

// whitelist paths that must be accessible without authentication so that
// assets, the login form itself and the health check are never blocked.
const PUBLIC_PATHS = [...OTHER_PUBLIC_PATHS, ...SITE_PATHS];

// files served from public/ and the generated metadata routes (icon, apple-icon, opengraph-image,
// robots.txt, sitemap.xml) are never private, so signed-out visitors and crawlers must reach them
const STATIC_FILE = /\.(?:png|jpe?g|gif|webp|avif|svg|ico|txt|xml|webmanifest|json|woff2?|mp4|webm|js|css)$/i;

// where a signed-out visitor goes. On the dashboard's own address that is its configured origin, so the address never
// comes from the request. Anywhere else it is the same address as before;
// the page that was asked for goes along as `next`, but only a dashboard path (see nextFor): the sign-in page checks it again.
function loginAddress(request: NextRequest): URL {
  const next = nextFor(request.nextUrl.pathname, request.nextUrl.search);
  if (hostKind(request.headers.get('host'), SPLIT) === 'app') {
    const url = new URL('/login', SPLIT.appOrigin);
    if (next) url.searchParams.set('next', next);
    return url;
  }
  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = '/login';
  loginUrl.search = '';
  if (next) loginUrl.searchParams.set('next', next);
  return loginUrl;
}

// the pages that need a session: the dashboard's own paths apart from sign-in and the invitation
const PRIVATE_PATHS = APP_PATHS.filter((p) => p !== '/login' && p !== '/accept-invite' && p !== '/reset-password');

// the script policy is set here and not in next.config.mjs, because the dashboard's needs a fresh nonce for every request. The public
// site pages keep a fixed policy (a nonce would make every one of them render per request and lose the CDN cache and they hold no
// credential: the access token is only ever on the dashboard's pages). The dashboard, sign-in and invitation pages are rendered per
// request (their layouts say so) and get the strict policy: no inline script runs unless it carries this request's nonce.
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const DEVELOPMENT = process.env.NODE_ENV !== 'production';
const SITE_CSP = buildCsp({
  apiUrl: API_URL,
  turnstileSiteKey: process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY,
  gaId: process.env.NEXT_PUBLIC_GA_ID,
  development: DEVELOPMENT,
});

// passes the request on with the policy for the surface it belongs to. A private page also gets the nonce on the request, which is how
// Next finds it and puts it on its own scripts.
function proceed(request: NextRequest, pathname: string, rewriteTo?: URL): NextResponse {
  const kind = hostKind(request.headers.get('host'), SPLIT);
  const strict = isPrivateSurface(pathname, kind, SPLIT);
  const headers = new Headers(request.headers);
  let policy = SITE_CSP;
  if (strict) {
    const nonce = btoa(crypto.randomUUID());
    policy = buildNonceCsp({ nonce, apiUrl: API_URL, development: DEVELOPMENT, scriptHashes: [themeScriptHash()] });
    headers.set('x-nonce', nonce);
    headers.set('Content-Security-Policy', policy);
  }
  const response = rewriteTo ? NextResponse.rewrite(rewriteTo, { request: { headers } }) : NextResponse.next({ request: { headers } });
  response.headers.set('Content-Security-Policy', policy);
  return response;
}

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  const decision = routeRequest({ host: request.headers.get('host'), pathname, search }, SPLIT);
  // a move of the www address is permanent (308). Every other redirect depends on the page and the address, so it is 307.
  if (decision.type === 'redirect') return NextResponse.redirect(decision.url, decision.permanent ? 308 : 307);
  if (decision.type === 'notfound') return new NextResponse('Not found', { status: 404 });
  if (decision.type === 'rewrite') {
    // the overview is "/" on the dashboard's address and "/dashboard" inside the app. It still needs a session.
    if (request.cookies.get(SIGNED_IN_COOKIE)?.value !== '1') return NextResponse.redirect(loginAddress(request));
    const url = request.nextUrl.clone();
    url.pathname = decision.pathname;
    return proceed(request, decision.pathname, url);
  }

  // pass through Next.js internals, static files and any whitelisted path
  // without checking auth - blocking these would break asset loading or cause
  // an infinite redirect loop on the login page itself.
  if (
    pathname.startsWith('/_next/') ||
    // Vercel serves its analytics script from /_vercel/. Redirecting it to the login page breaks the script locally.
    pathname.startsWith('/_vercel/') ||
    pathname.startsWith('/api/') ||
    // a file extension only exempts a real file. A dashboard page that ends in ".png" still needs a session.
    (STATIC_FILE.test(pathname) && !PRIVATE_PATHS.some((p) => pathname === p || pathname.startsWith(p + '/'))) ||
    // on the dashboard's own address "/" is the overview and needs a session. On the site's address it is the home page.
    (PUBLIC_EXACT.includes(pathname) && !SPLIT.split) ||
    (PUBLIC_EXACT.includes(pathname) && SPLIT.split && hostKind(request.headers.get('host'), SPLIT) !== 'app') ||
    PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(p + '/'))
  ) {
    return proceed(request, pathname);
  }

  // an address that belongs to neither half is a mistyped one: show the 404 page, not a sign-in for a product they may not use
  if (!PRIVATE_PATHS.some((p) => pathname === p || pathname.startsWith(p + '/'))) return proceed(request, pathname);

  const marker = request.cookies.get(SIGNED_IN_COOKIE)?.value;
  if (marker !== '1') return NextResponse.redirect(loginAddress(request));

  // a machine's address ends in its id, which is a UUID. Anything else is not a machine: it gets the 404 page with a 404 status (the layout
  // checks too, but a page that streams has already sent 200 by then).
  const machine = /^\/devices\/([^/]+)/.exec(pathname);
  if (machine) {
    let id = machine[1];
    try {
      id = decodeURIComponent(id);
    } catch {
      // an address that cannot be decoded is not a UUID either
    }
    if (!isUuid(id)) {
      const gone = request.nextUrl.clone();
      gone.pathname = '/not-a-machine';
      return proceed(request, pathname, gone);
    }
  }

  return proceed(request, pathname);
}

export const config = {
  // match every route so the proxy runs for all pages, then the early
  // return above exempts the paths that must remain public.
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
