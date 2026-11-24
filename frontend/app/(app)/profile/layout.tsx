import type { Metadata } from 'next';

// these pages are client components and cannot export metadata, so the tab title comes from this layout.
// the root template adds the brand, so the title is only the page's own name.
export const metadata: Metadata = { title: 'Profile' };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
