import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import LegalPage from '@/components/content/LegalPage';
import { getLegalPage, legalMetadata } from '@/lib/legalSource';

export function generateMetadata(): Metadata {
  return legalMetadata('accessibility', 'Accessibility');
}

// static: the text is the Markdown file content/legal/accessibility.md
export default function Page() {
  const doc = getLegalPage('accessibility');
  if (!doc) notFound();
  return <LegalPage doc={doc} />;
}
