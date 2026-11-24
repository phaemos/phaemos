import type { Metadata } from 'next';
import { Exo_2, IBM_Plex_Mono, Manrope } from 'next/font/google';
import AnalyticsGuard from '@/components/AnalyticsGuard';
import VercelAnalytics from '@/components/VercelAnalytics';
import ToastContainer from '@/components/ui/Toast';
import { ToastProvider } from '@/hooks/useToast';
import { SPLIT } from '@/lib/links';
import { THEME_COLOR } from '@/lib/theme';
import { themeScriptHash } from '@/lib/themeHash.mjs';
import './globals.css';

// the three typefaces live only here, behind CSS variables that the rest of the code reads (--typeface-display, --typeface-sans
// and --typeface-mono in tailwind.config.ts and globals.css). Each has one job: Exo 2 is the brand's face for the name and page
// headings, Manrope is for reading and the interface and IBM Plex Mono is for code, readings with units and ids. They are
// self-hosted at build time through next/font with size-matched fallbacks. Each is trimmed to the weights in use.
const display = Exo_2({ subsets: ['latin'], weight: ['600'], variable: '--typeface-display', display: 'swap' });
const sans = Manrope({ subsets: ['latin'], weight: ['400', '500', '600', '700'], variable: '--typeface-sans', display: 'swap' });
const mono = IBM_Plex_Mono({ subsets: ['latin'], weight: ['400', '500', '600'], variable: '--typeface-mono', display: 'swap' });

// the address of the public site, for absolute addresses in the page metadata (canonical, share image). With one address
// and no value set it is the production address, as the sitemap already used.
const SITE_ORIGIN = SPLIT.split ? SPLIT.siteOrigin : (process.env.NEXT_PUBLIC_SITE_URL || 'https://phaemos.com').replace(/\/+$/, '');

export const metadata: Metadata = {
  metadataBase: new URL(SITE_ORIGIN),
  title: { default: 'PHAEMOS', template: '%s | PHAEMOS' },
  description: 'Reveal before failure: live machine monitoring, anomaly scoring and maintenance tickets.',
  applicationName: 'PHAEMOS',
  // each public page has its own share image (opengraph-image.tsx beside it); these are the fields every page shares
  openGraph: { siteName: 'PHAEMOS', type: 'website', locale: 'en_GB' },
  twitter: { card: 'summary_large_image' },
};

// the root holds only what every page shares. The public site, the sign-in page and the dashboard each
// bring their own shell from their route group layout.
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${sans.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        <meta name="theme-color" content={THEME_COLOR.dark} />
        {/* applies the stored theme before the page paints, so the wrong one never flashes. It is a file and not inline script, so the
            dashboard's policy can forbid inline script altogether (public/theme.js, which holds the two colours of lib/theme.ts). */}
        {/* synchronous on purpose: it must run before the first paint or the wrong theme flashes */}
        {/* eslint-disable-next-line @next/next/no-sync-scripts */}
        <script src="/theme.js" integrity={themeScriptHash()} />
      </head>
      <body className="min-h-screen bg-surface-50 text-surface-900 dark:bg-surface-950 dark:text-surface-50">
        <ToastProvider>
          {children}
          <ToastContainer />
        </ToastProvider>
        {/* Vercel Web Analytics is optional like Google Analytics: it is off unless NEXT_PUBLIC_VERCEL_ANALYTICS is 1. The legal pages follow the same value (content/legal/services.ts). In development the package loads a debug script from va.vercel-scripts.com, which the CSP blocks, so it only mounts in production and only on Vercel (NEXT_PUBLIC_ON_VERCEL, set in next.config.mjs from VERCEL at build time), where it loads /_vercel/insights/script.js from this origin. It counts only the public site pages (lib/publicPaths.ts) */}
        {process.env.NODE_ENV === 'production' && process.env.NEXT_PUBLIC_ON_VERCEL === '1' && process.env.NEXT_PUBLIC_VERCEL_ANALYTICS === '1' && <VercelAnalytics />}
        <AnalyticsGuard />
      </body>
    </html>
  );
}

