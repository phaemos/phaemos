import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import LegalPage from '@/components/content/LegalPage';
import { getLegalPage, legalMetadata } from '@/lib/legalSource';

export function generateMetadata(): Metadata {
  return legalMetadata('terms', 'Terms of use');
}

// static: the text is the Markdown file content/legal/terms.md
export default function Page() {
  const doc = getLegalPage('terms');
  if (!doc) notFound();
  return <LegalPage doc={doc} />;
}
