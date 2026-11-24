import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import ChangelogView from '@/components/website/ChangelogView';
import { FILTERS, hasItems, isFilter } from '@/lib/changelog';
import { loadReleases } from '@/lib/changelogSource';

// one static page per filter value, so a filtered view has its own link and needs no script
export const dynamicParams = false;

export function generateStaticParams() {
  return FILTERS.map((type) => ({ type }));
}

export async function generateMetadata({ params }: { params: Promise<{ type: string }> }): Promise<Metadata> {
  const { type } = await params;
  if (!isFilter(type)) return {};
  return {
    title: `Changelog: ${type}`,
    description: `The PHAEMOS releases that list ${type} changes, newest first.`,
  };
}

export default async function ChangelogFilterPage({ params }: { params: Promise<{ type: string }> }) {
  const { type } = await params;
  if (!isFilter(type)) notFound();
  const releases = loadReleases().filter((r) => !r.unreleased || hasItems(r));
  return <ChangelogView releases={releases} filter={type} />;
}
