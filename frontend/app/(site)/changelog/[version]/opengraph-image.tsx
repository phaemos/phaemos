import { findRelease, hasItems, summarise } from '@/lib/changelog';
import { loadReleases } from '@/lib/changelogSource';
import { OG_SIZE, OG_TYPE, ogImage } from '@/lib/ogImage';

export const size = OG_SIZE;
export const contentType = OG_TYPE;
export const alt = 'PHAEMOS release notes';

// built once per release at build time, like the release page. The changelog file is not in the running image, so nothing
// here may be drawn on demand.
export const dynamicParams = false;

export function generateStaticParams() {
  return loadReleases().filter((r) => !r.unreleased || hasItems(r)).map((r) => ({ version: r.slug }));
}

// each release's card carries its version and the first line of its summary
export default async function Image({ params }: { params: Promise<{ version: string }> }) {
  const { version } = await params;
  let decoded = version;
  try {
    decoded = decodeURIComponent(version);
  } catch {
    // an address that does not decode is used as it came
  }
  const release = findRelease(loadReleases().filter((r) => !r.unreleased || hasItems(r)), decoded);
  const title = !release ? 'Release notes' : release.unreleased ? 'Next release' : `Version ${release.version}`;
  const line = release ? summarise(release) : '';
  return ogImage(title, line.length > 140 ? `${line.slice(0, 137).replace(/\s+\S*$/, '')}…` : line || undefined);
}
