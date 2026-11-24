import type { Metadata } from 'next';
import ErrorBoundary from '@/components/ui/ErrorBoundary';

// the sign-in and invitation pages are not for a search engine. This sets no title, so the root template reaches them.
export const metadata: Metadata = { robots: { index: false, follow: false } };

// rendered for each request, because the strict script policy of these pages carries a nonce made for that request (proxy.ts)
export const dynamic = 'force-dynamic';

// the sign-in page stands alone: a centred card, no navigation. Navigation and a sign-out button mean nothing before signing in.
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main id="main" tabIndex={-1} className="flex min-h-[calc(100dvh-var(--cookie-banner-height,0px))] items-center justify-center px-4 py-10 outline-none">
      <ErrorBoundary>{children}</ErrorBoundary>
    </main>
  );
}
