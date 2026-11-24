import type { Metadata } from 'next';

// the page is a client component and cannot export metadata, so the tab title comes from this layout. The group layout
// sets no title of its own, which lets the root template ("%s | PHAEMOS") reach every page in the group.
export const metadata: Metadata = { title: 'Sign in' };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
