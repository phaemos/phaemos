import type { Metadata } from 'next';
import { Analytics } from '@vercel/analytics/next';
import Sidebar from '@/components/Sidebar';
import ErrorBoundary from '@/components/ui/ErrorBoundary';
import ToastContainer from '@/components/ui/Toast';
import { ToastProvider } from '@/hooks/useToast';
import CookieBanner from '@/components/CookieBanner';
import GoogleAnalytics from '@/components/GoogleAnalytics';
import './globals.css';

export const metadata: Metadata = {
  title: 'PHAEMOS',
  description: 'Smart Maintenance Platform',
};

// I apply the stored theme class before the page renders to prevent a flash
// of the wrong theme during hydration.
const themeScript = `
(function() {
  var t = localStorage.getItem('theme');
  if (t === 'light') { document.documentElement.classList.remove('dark'); }
  else { document.documentElement.classList.add('dark'); }
})();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="bg-surface-50 dark:bg-surface-950 text-surface-900 dark:text-surface-50 min-h-screen">
        <ToastProvider>
          <div className="flex h-screen overflow-hidden">
            <Sidebar />
            <main className="flex-1 overflow-y-auto">
              <ErrorBoundary>{children}</ErrorBoundary>
            </main>
          </div>
          <ToastContainer />
          <CookieBanner />
        </ToastProvider>
        <Analytics />
        <GoogleAnalytics />
      </body>
    </html>
  );
}
