import type { Metadata } from 'next';
import ChangelogView from '@/components/website/ChangelogView';
import { hasItems } from '@/lib/changelog';
import { loadReleases } from '@/lib/changelogSource';

export const metadata: Metadata = {
  title: 'Changelog',
  description: 'Every PHAEMOS release with its date, a summary and the full notes, filterable by added, changed, fixed, security and removed.',
};

// static: the changelog is read once at build time
export default function ChangelogPage() {
  // an Unreleased block with nothing in it is not shown
  const releases = loadReleases().filter((r) => !r.unreleased || hasItems(r));
  return <ChangelogView releases={releases} />;
}
