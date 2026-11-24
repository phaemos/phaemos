'use client';

import { Analytics } from '@vercel/analytics/next';
import { SPLIT } from '@/lib/links';
import { scopeAnalytics } from '@/lib/publicPaths';

// a client component because the package takes a function, which cannot cross from a server component. Only the
// public site pages are counted: see lib/publicPaths.ts. With two addresses nothing on the dashboard's address is counted.
export default function VercelAnalytics() {
  return <Analytics beforeSend={(event) => scopeAnalytics(event, SPLIT.split ? SPLIT.appHost : undefined)} />;
}
