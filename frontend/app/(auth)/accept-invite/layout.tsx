import type { Metadata } from 'next';

// the page is a client component and cannot export metadata, so the tab title comes from this layout.
export const metadata: Metadata = { title: 'Accept invitation' };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
