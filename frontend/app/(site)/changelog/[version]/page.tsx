import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import ReactMarkdown from 'react-markdown';
import Time from '@/components/ui/Time';
import Breadcrumbs from '@/components/content/Breadcrumbs';
import { findRelease, hasItems, sectionTitle, summarise, versionHref, type Release } from '@/lib/changelog';
import { loadReleases } from '@/lib/changelogSource';

// only versions in the file exist. Anything else is a 404 and nothing is rendered on demand.
export const dynamicParams = false;

function listed(): Release[] {
  return loadReleases().filter((r) => !r.unreleased || hasItems(r));
}

export function generateStaticParams() {
  return listed().map((r) => ({ version: r.slug }));
}

// the segment may arrive encoded or decoded depending on the caller
function decode(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

export async function generateMetadata({ params }: { params: Promise<{ version: string }> }): Promise<Metadata> {
  const { version } = await params;
  const release = findRelease(listed(), decode(version));
  if (!release) return {};
  const name = release.unreleased ? 'Next release' : `Version ${release.version}`;
  return {
    title: `${name} release notes`,
    description: summarise(release) || `Release notes for PHAEMOS ${release.version}.`,
  };
}

// code, links and lists keep 4.5:1 or better in both themes. Long strings break instead of widening the page.
const PROSE = [
  'prose prose-sm max-w-[72ch] break-words dark:prose-invert sm:prose-base',
  'prose-p:text-surface-700 dark:prose-p:text-surface-300',
  'prose-li:text-surface-700 dark:prose-li:text-surface-300 prose-li:marker:text-surface-600 dark:prose-li:marker:text-surface-400',
  'prose-ul:my-3 prose-li:my-1.5',
  'prose-strong:text-surface-900 dark:prose-strong:text-surface-50',
  'prose-a:text-brand-800 prose-a:underline prose-a:underline-offset-2 hover:prose-a:no-underline dark:prose-a:text-brand-400 prose-a:[overflow-wrap:anywhere]',
  'prose-code:rounded prose-code:bg-surface-100 prose-code:px-1 prose-code:py-0.5 prose-code:font-mono prose-code:text-[max(0.8125rem,0.9em)] prose-code:font-normal',
  'prose-code:text-surface-900 dark:prose-code:bg-surface-800 dark:prose-code:text-surface-50',
  'prose-code:before:content-none prose-code:after:content-none prose-code:[overflow-wrap:anywhere]',
].join(' ');

const navLink =
  'inline-flex min-h-[44px] items-center text-brand-800 underline underline-offset-2 hover:no-underline dark:text-brand-400';

export default async function ReleasePage({ params }: { params: Promise<{ version: string }> }) {
  const { version } = await params;
  const releases = listed();
  const index = releases.findIndex((r) => r.slug === decode(version));
  if (index === -1) notFound();
  const release = releases[index];
  const newer = releases[index - 1];
  const older = releases[index + 1];
  const title = release.unreleased ? 'Next release' : `Version ${release.version}`;
  const label = (r: Release) => (r.unreleased ? 'Next release' : r.version);

  return (
    <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6 md:py-16">
      <div className="max-w-3xl">
      <Breadcrumbs trail={[{ name: 'Changelog', href: '/changelog' }]} current={title} />

      <header className="mt-4 border-b border-surface-200 pb-6 dark:border-surface-800">
        <h1 className={`${release.unreleased ? '' : 'tnum '}break-words text-3xl font-semibold tracking-[-0.02em] text-surface-900 dark:text-surface-50 md:text-4xl`}>{title}</h1>
        <p className={`mt-2 text-base text-surface-600 dark:text-surface-400`}>
          {release.date ? <Time value={release.date} format="date" /> : 'Not yet released. These notes may change.'}
        </p>
      </header>

      <div className="mt-8 space-y-10">
        {release.preamble && (
          <div className={PROSE}>
            <ReactMarkdown>{release.preamble}</ReactMarkdown>
          </div>
        )}
        {release.sections
          .filter((s) => s.body)
          .map((s, i) => (
            <section key={`${s.name}-${i}`} aria-labelledby={`section-${i}`}>
              <h2 id={`section-${i}`} className="mb-3 text-2xl font-semibold tracking-[-0.01em] text-surface-900 dark:text-surface-50">
                {s.kind === 'other' ? s.name : sectionTitle(s.kind)}
                <span className="tnum ml-3 align-middle text-base font-normal text-surface-600 dark:text-surface-400">{s.items.length > 0 ? `${s.items.length} ${s.items.length === 1 ? 'item' : 'items'}` : ''}</span>
              </h2>
              <div className={PROSE}>
                <ReactMarkdown>{s.body}</ReactMarkdown>
              </div>
            </section>
          ))}
      </div>

      <nav aria-label="Other releases" className="mt-12 flex flex-wrap justify-between gap-x-8 gap-y-2 border-t border-surface-200 pt-4 dark:border-surface-800">
        {older ? (
          <Link href={versionHref(older)} className={navLink}>
            Older release: <span className={`${older.unreleased ? '' : 'tnum '}ml-1`}>{label(older)}</span>
          </Link>
        ) : (
          <span />
        )}
        {newer && (
          <Link href={versionHref(newer)} className={navLink}>
            Newer release: <span className={`${newer.unreleased ? '' : 'tnum '}ml-1`}>{label(newer)}</span>
          </Link>
        )}
      </nav>
      </div>
    </div>
  );
}
