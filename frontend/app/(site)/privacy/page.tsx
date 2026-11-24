import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import LegalPage from '@/components/content/LegalPage';
import { getLegalPage, legalMetadata } from '@/lib/legalSource';

export function generateMetadata(): Metadata {
  return legalMetadata('privacy', 'Privacy notice');
}

// static: the text is the Markdown file content/legal/privacy.md
export default function Page() {
  const doc = getLegalPage('privacy');
  if (!doc) notFound();
  return <LegalPage doc={doc} />;
}
