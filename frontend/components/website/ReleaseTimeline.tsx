import Link from 'next/link';
import { Fragment } from 'react';
import { countByKind, releaseYear, sectionTitle, summarise, versionHref, type FilterKind, type Release, type SectionKind } from '@/lib/changelog';
import Time from '@/components/ui/Time';

const CHIP_ORDER: readonly SectionKind[] = ['security', 'added', 'changed', 'fixed', 'removed', 'deprecated', 'other'];

interface Props {
  releases: Release[];
  headingLevel?: 2 | 3;
  // a filter makes each summary come from that section
  filter?: FilterKind;
  yearMarkers?: boolean;
}

// the dated timeline shared by the changelog and the home page. The rail is decorative and carries an id so a
// reading-position marker can be attached to it later. Entries are an ordered list of articles.
export default function ReleaseTimeline({ releases, headingLevel = 2, filter, yearMarkers = true }: Props) {
  const Heading = headingLevel === 2 ? 'h2' : 'h3';
  // the releases that open a new year, worked out before rendering so the map below stays pure
  const yearStarts = new Set<string>();
  if (yearMarkers) {
    let previous: string | null = null;
    for (const r of releases) {
      const y = releaseYear(r);
      if (y && y !== previous) yearStarts.add(r.slug);
      if (y) previous = y;
    }
  }

  return (
    <div className="relative" data-timeline>
      <div
        id="changelog-rail"
        aria-hidden="true"
        className="absolute bottom-3 left-2 top-3 w-px bg-surface-300 dark:bg-surface-700 md:left-[8rem]"
      />
      <ol className="relative">
        {releases.map((release) => {
          const year = releaseYear(release);
          const showYear = yearStarts.has(release.slug);
          const counts = countByKind(release);
          const summary = summarise(release, filter);
          const title = release.unreleased ? 'Next release' : release.version;
          return (
            <Fragment key={release.slug}>
              {showYear && (
                <li aria-hidden="true" className="relative pb-4 pl-8 pt-2 md:grid md:grid-cols-[7rem_2rem_1fr] md:pl-0">
                  <span className="label tnum text-surface-700 dark:text-surface-300 md:col-start-3">{year}</span>
                </li>
              )}
              <li className="relative pb-10 pl-8 md:grid md:grid-cols-[7rem_2rem_1fr] md:pl-0">
                <span
                  aria-hidden="true"
                  className={
                    release.unreleased
                      ? 'absolute left-[3.5px] top-[7px] h-[9px] w-[9px] rounded-full border border-dashed border-surface-600 bg-surface-50 dark:border-surface-400 dark:bg-surface-950 md:left-[calc(8rem-4.5px)]'
                      : 'absolute left-[3.5px] top-[7px] h-[9px] w-[9px] bg-surface-700 dark:bg-surface-300 md:left-[calc(8rem-4.5px)]'
                  }
                />
                <article className="min-w-0 md:col-start-3 md:row-start-1">
                  <p className={`${release.date ? 'tnum ' : ''}mb-1 text-meta leading-6 text-surface-600 dark:text-surface-400 md:hidden`}>
                    {release.date ? <Time value={release.date} format="date" /> : 'Not yet released'}
                  </p>
                  <Heading className={`${release.unreleased ? '' : 'tnum '}break-words text-2xl font-semibold tracking-[-0.01em] text-surface-900 dark:text-surface-50`}>{title}</Heading>
                  {summary && <p className="mt-2 max-w-[72ch] break-words text-surface-700 dark:text-surface-300">{summary}</p>}
                  <ul aria-label={`Changes in ${title}`} className="mt-3 flex flex-wrap gap-2">
                    {CHIP_ORDER.filter((k) => counts[k]).map((k) => (
                      <li key={k} className="rounded-md border border-surface-300 px-2 py-0.5 text-meta text-surface-700 dark:border-surface-700 dark:text-surface-300">
                        <span className="tnum">{counts[k]}</span> {k === 'other' ? 'other' : sectionTitle(k).toLowerCase()}
                      </li>
                    ))}
                  </ul>
                  <Link
                    href={versionHref(release)}
                    className="mt-1 inline-flex min-h-[44px] items-center text-brand-800 underline underline-offset-2 hover:no-underline dark:text-brand-400"
                  >
                    Read release notes<span className="sr-only"> for {title}</span>
                  </Link>
                </article>
                <p className={`${release.date ? 'tnum ' : ''}hidden text-meta leading-6 text-surface-600 dark:text-surface-400 md:col-start-1 md:row-start-1 md:block md:pt-[2px] md:text-right`}>
                  {release.date ? <Time value={release.date} format="date" /> : 'Not yet released'}
                </p>
              </li>
            </Fragment>
          );
        })}
      </ol>
    </div>
  );
}
