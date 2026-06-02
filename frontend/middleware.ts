import { NextRequest, NextResponse } from 'next/server';

// I whitelist paths that must be accessible without authentication so that
// assets, the login form itself, and the health check are never blocked.
const PUBLIC_PATHS = [
  '/login',
  '/favicon.ico',
];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // I pass through Next.js internals, static files and any whitelisted path
  // without checking auth - blocking these would break asset loading or cause
  // an infinite redirect loop on the login page itself.
  if (
    pathname.startsWith('/_next/') ||
    pathname.startsWith('/api/') ||
    PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(p + '/'))
  ) {
    return NextResponse.next();
  }

  const token = request.cookies.get('token')?.value;
  if (!token) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = '/login';
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  // I match every route so the middleware runs for all pages, then the early
  // return above exempts the paths that must remain public.
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
