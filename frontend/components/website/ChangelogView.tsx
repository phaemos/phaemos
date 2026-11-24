import PageHeader from '@/components/ui/PageHeader';
import Tabs, { type TabItem } from '@/components/ui/Tabs';
import ReleaseTimeline from '@/components/website/ReleaseTimeline';
import { FILTERS, hasKind, type FilterKind, type Release } from '@/lib/changelog';

type TabValue = 'all' | FilterKind;

// the filter tabs are plain links to one static page per filter, so a filtered view has its own address and
// everything works without script
export function filterHref(value: TabValue): string {
  return value === 'all' ? '/changelog' : `/changelog/filter/${value}`;
}

// the list page body: header, filter tabs and the timeline. Used by /changelog and /changelog/filter/[type].
export default function ChangelogView({ releases, filter }: { releases: Release[]; filter?: FilterKind }) {
  const items: TabItem<TabValue>[] = [
    { value: 'all', label: 'All', href: filterHref('all'), count: releases.length },
    ...FILTERS.map((f) => ({
      value: f as TabValue,
      label: f.charAt(0).toUpperCase() + f.slice(1),
      href: filterHref(f),
      count: releases.filter((r) => hasKind(r, f)).length,
    })),
  ];
  const shown = filter ? releases.filter((r) => hasKind(r, filter)) : releases;

  return (
    <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6 md:py-16">
      <PageHeader
        variant="site"
        title="Changelog"
        description="What changed in each PHAEMOS release, newest first. The notes are the CHANGELOG.md file in the repository."
      />
      <Tabs className="mt-8" items={items} value={filter ?? 'all'} label="Filter releases by type of change" />
      <p className="mt-4 text-base text-surface-600 dark:text-surface-400" role="status">
        {filter ? (
          <>
            <span className="tnum">{shown.length}</span> of <span className="tnum">{releases.length}</span> entries list {filter} changes.
          </>
        ) : (
          <>
            <span className="tnum">{releases.length}</span> entries.
          </>
        )}
      </p>
      <div className="mt-8">
        {shown.length > 0 ? (
          <ReleaseTimeline releases={shown} filter={filter} />
        ) : (
          <p className="text-surface-700 dark:text-surface-300">No release lists {filter} changes.</p>
        )}
      </div>
    </div>
  );
}
