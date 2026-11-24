import { existsSync, readFileSync } from 'fs';
import { join } from 'path';
import { parseChangelog, type Release } from './changelog';

let cached: Release[] | null = null;

// reads CHANGELOG.md at build time so every changelog page stays static. The monorepo path comes first (the build
// is rooted at frontend/ and the repository root is one folder up). A copy placed inside frontend/ at build time
// is the second choice, for a build that cannot see the folder above. With neither, the build stops: an empty
// changelog on a live site would hide the fault.
export function loadReleases(): Release[] {
  if (cached) return cached;
  const candidates = [join(process.cwd(), '..', 'CHANGELOG.md'), join(process.cwd(), 'CHANGELOG.md')];
  const found = candidates.find((p) => existsSync(p));
  if (!found) {
    throw new Error(`CHANGELOG.md not found. Looked in: ${candidates.join(' and ')}. Provide one of them at build time.`);
  }
  cached = parseChangelog(readFileSync(found, 'utf8'));
  return cached;
}
