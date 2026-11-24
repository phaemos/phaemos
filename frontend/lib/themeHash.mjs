// the content hash of public/theme.js, as a CSP source ('sha256-...') and as the integrity value of its script tag. The dashboard's
// policy allows no script by address (with 'strict-dynamic' an address allow-list is ignored) and no inline script, so this one small
// file, which must run before the page paints, is allowed by its hash: it runs only if its bytes are exactly these.
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

let cached = null;

export function themeScriptHash() {
  // the file never changes in a built app, so production reads it once. The development server reads it every time, so an edit
  // to the script never leaves a stale hash that blocks it.
  if (cached && process.env.NODE_ENV === 'production') return cached;
  const file = readFileSync(join(process.cwd(), 'public', 'theme.js'));
  cached = `sha256-${createHash('sha256').update(file).digest('base64')}`;
  return cached;
}
