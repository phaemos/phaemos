import type { Metadata } from 'next';
import SiteHeader from '@/components/website/SiteHeader';
import SiteFooter from '@/components/website/SiteFooter';
import CookieBanner from '@/components/CookieBanner';
import GoogleAnalytics from '@/components/GoogleAnalytics';
import ErrorBoundary from '@/components/ui/ErrorBoundary';

// each public page names itself as its own canonical address, resolved against metadataBase (the site's address)
export const metadata: Metadata = { alternates: { canonical: './' } };

// the public shell: a sticky top nav, the page and a footer. It ends above the cookie banner, which is fixed to the
// bottom of the screen and publishes its height in --cookie-banner-height while it shows.
export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
    {/* the cookie banner and Google Analytics run on the public site only. The dashboard, the sign-in page and the invitation page
        never load the tag, because their addresses carry machine ids and an invitation token. The banner comes first in the
        page order so keyboard and screen reader users meet it before the content. */}
    <CookieBanner />
    <GoogleAnalytics />
    <div className="site-shell flex min-h-[calc(100dvh-var(--cookie-banner-height,0px))] flex-col pb-[var(--cookie-banner-height,0px)]">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-lg focus:bg-brand-700 focus:px-4 focus:py-3 focus:text-white">
        Skip to content
      </a>
      <SiteHeader />
      <main id="main" tabIndex={-1} className="flex-1 outline-none">
        <ErrorBoundary>{children}</ErrorBoundary>
      </main>
      <SiteFooter />
    </div>
    </>
  );
}
