import type { Metadata } from 'next';
import ContactSent from '@/components/website/ContactSent';

// a page reached only after a send, so it is kept out of search results and the sitemap
export const metadata: Metadata = {
  title: 'Message sent',
  description: 'Your message reached us.',
  robots: { index: false, follow: false },
};

export default function ContactSentPage() {
  return <ContactSent />;
}
