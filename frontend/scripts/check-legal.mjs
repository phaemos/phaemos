// lists every placeholder still open in the legal pages, with its file and line. It stops a production build while any
// that a visitor could see remains. Runs before every build (see "prebuild" in package.json).
//
// what counts as a placeholder: any [words] in the text that is not followed by "(" (a link is [text](address)) or a
// "version" that is not a real calendar day. A placeholder in a passage for a service that is switched off is hidden from
// visitors and is listed apart, not counted.
//
// what counts as production: VERCEL_ENV=production (a Vercel production deployment) or NODE_ENV=production when the
// build is not on Vercel (a Docker or self-hosted build). A Vercel preview and a local build with no NODE_ENV only warn.
// LEGAL_PLACEHOLDERS overrides the decision: "fail" always stops the build, "allow" never does.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { badVersionLine, scanPlaceholders } from '../lib/legal.ts';
import { LEGAL_VARS, SERVICES } from '../content/legal/services.ts';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const legalDir = join(root, 'content', 'legal');
const found = [];

for (const name of readdirSync(legalDir).filter((f) => f.endsWith('.md')).sort()) {
  const raw = readFileSync(join(legalDir, name), 'utf8');
  for (const hit of scanPlaceholders(raw, SERVICES, LEGAL_VARS)) found.push({ file: `content/legal/${name}`, ...hit });
  const line = badVersionLine(raw);
  if (line !== null) found.push({ file: `content/legal/${name}`, name: 'version is not a real date (YYYY-MM-DD)', line, active: true });
}

// the rest of the site's source: a page, a component or a blog post must not ship with a placeholder either. A placeholder
// is written the same way as in the legal pages, in capitals inside square brackets ([LEGAL NAME OF THE CONTROLLER]), so
// any business detail the site is still waiting for can be left in plain sight and this stops the build until it is filled.
// two words at least, so a computed key in code ([PUMP]) is never mistaken for one.
const SITE_PLACEHOLDER = /\[([A-Z][A-Z0-9,.:'\/-]*(?: [A-Z0-9,.:'\/-]+)+)\](?!\()/g;
function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (/\.(tsx?|mdx?|txt)$/.test(name) && !/\.test\./.test(name)) out.push(path);
  }
  return out;
}
for (const dir of ['app', 'components', join('content', 'blog'), 'public']) {
  for (const path of walk(join(root, dir))) {
    readFileSync(path, 'utf8').split('\n').forEach((text, i) => {
      for (const m of text.matchAll(SITE_PLACEHOLDER)) found.push({ file: path.slice(root.length + 1), name: m[1], line: i + 1, active: true });
    });
  }
}

const open = found.filter((h) => h.active);
const hidden = found.filter((h) => !h.active);

if (open.length === 0) {
  console.log('legal: no placeholders left in the legal pages or the site.');
} else {
  console.log(`legal: ${open.length} placeholder${open.length === 1 ? '' : 's'} still open in the legal pages and the site:`);
  for (const h of open) console.log(`  ${h.file}:${h.line}  [${h.name}]`);
}
if (hidden.length > 0) {
  console.log(`legal: ${hidden.length} more in passages for services that are switched off (content/legal/services.ts):`);
  for (const h of hidden) console.log(`  ${h.file}:${h.line}  [${h.name}]`);
}

// the service flags in content/legal/services.ts are set by hand. Where this build can see the settings that switch a service on
// (a build run beside the API's environment or one that was handed the same values), a service that is on while its flag is
// off means the notice leaves out a service that is in use. That is a mismatch and it stops a production build like a placeholder;
// a build that cannot see them (the usual case on Vercel, which holds no API settings) has nothing to compare and says so.
const SETTINGS = {
  analytics: ['NEXT_PUBLIC_GA_ID'],
  brevo: ['BREVO_API_KEY'],
  google: ['GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET'],
  github: ['GITHUB_CLIENT_ID', 'GITHUB_CLIENT_SECRET'],
  microsoft: ['MICROSOFT_CLIENT_ID', 'MICROSOFT_CLIENT_SECRET'],
  discord: ['DISCORD_WEBHOOK_URL'],
};
const mismatches = [];
let seen = 0;
for (const [flag, names] of Object.entries(SETTINGS)) {
  const set = names.filter((n) => (process.env[n] ?? '').trim() !== '');
  if (names.some((n) => n in process.env)) seen += 1;
  if (set.length > 0 && !SERVICES[flag]) mismatches.push(`${flag} is off in content/legal/services.ts but ${set.join(' and ')} ${set.length === 1 ? 'is' : 'are'} set here`);
}
if (mismatches.length > 0) {
  console.log(`legal: ${mismatches.length} service flag${mismatches.length === 1 ? '' : 's'} disagree with the environment this build can see:`);
  for (const m of mismatches) console.log(`  ${m}`);
} else if (seen === 0) {
  console.log('legal: this build sees none of the settings that switch a service on, so the flags in services.ts are not compared. Set them by hand to match production.');
}

const override = process.env.LEGAL_PLACEHOLDERS;
const production = process.env.VERCEL_ENV ? process.env.VERCEL_ENV === 'production' : process.env.NODE_ENV === 'production';
const stop = override === 'fail' || (override !== 'allow' && production);

if ((open.length > 0 || mismatches.length > 0) && stop) {
  console.error(
    `legal: this is a production build${override === 'fail' ? ' (LEGAL_PLACEHOLDERS=fail)' : ''}, so it stops while a placeholder is open or a service flag disagrees with the environment. Fix what is listed above. ` +
      'To build anyway, for example to try the site, set LEGAL_PLACEHOLDERS=allow.',
  );
  process.exit(1);
}
if (open.length > 0 || mismatches.length > 0) {
  console.log(
    override === 'allow'
      ? 'legal: LEGAL_PLACEHOLDERS=allow is set, so this is only a warning. Those pages are noindex and left out of the sitemap until they are finished.'
      : 'legal: not a production build, so this is only a warning. Those pages are noindex and left out of the sitemap until they are finished.',
  );
}
