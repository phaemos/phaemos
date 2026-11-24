import type { Metadata } from 'next';
import AppShell from '@/components/shell/AppShell';

// the dashboard is never for a search engine. robots.txt on the dashboard's address says the same.
export const metadata: Metadata = { robots: { index: false, follow: false } };

// rendered for each request, because the strict script policy of these pages carries a nonce made for that request (proxy.ts)
export const dynamic = 'force-dynamic';

// every page behind sign-in: sidebar and the page (a bar below 1024 px). The proxy redirects a signed-out visitor to /login.
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
