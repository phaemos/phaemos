import type { Metadata } from 'next';
import Link from 'next/link';
import ThemeToggle from '@/components/ui/ThemeToggle';
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
      <body className="bg-gray-950 dark:bg-gray-950 text-gray-100 dark:text-gray-100 min-h-screen">
        <nav className="border-b border-gray-800 px-6 py-3 flex items-centre gap-6 text-sm">
          <span className="font-bold text-gray-100 tracking-tight mr-2">PHAEMOS</span>
          <Link href="/"        className="text-gray-400 hover:text-gray-100 transition-colours">Dashboard</Link>
          <Link href="/compare" className="text-gray-400 hover:text-gray-100 transition-colours">Compare</Link>
          <Link href="/alerts"  className="text-gray-400 hover:text-gray-100 transition-colours">Alerts</Link>
          <Link href="/tickets" className="text-gray-400 hover:text-gray-100 transition-colours">Tickets</Link>
          <Link href="/devices" className="text-gray-400 hover:text-gray-100 transition-colours">Devices</Link>
          <Link href="/admin"   className="text-gray-400 hover:text-gray-100 transition-colours ml-auto">Admin</Link>
          <ThemeToggle />
        </nav>
        {children}
      </body>
    </html>
  );
}
