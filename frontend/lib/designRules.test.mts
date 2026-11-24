// the design rules that must not creep back. This scans the source under app/ and components/ and fails with the file
// and line of each break. A real exception goes in ALLOW with the reason beside it: a rule is never switched off quietly.
// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const ROOT = new URL('..', import.meta.url).pathname;

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (/\.(tsx|ts|css)$/.test(name)) out.push(path);
  }
  return out;
}

const FILES = [...walk(join(ROOT, 'app')), ...walk(join(ROOT, 'components'))].map((path) => ({
  path,
  name: relative(ROOT, path),
  lines: readFileSync(path, 'utf8').split('\n'),
}));

// file (or file:line pattern) -> reason. Keyed by rule so an exception for one rule never covers another.
const ALLOW: Record<string, Record<string, string>> = {
  'mono-on-label': {
    'components/website/SensorTable.tsx': 'the row header of the sensor table is a part number (BME280), which is data and not a label',
  },
  'hex-colour': {
    'app/globals.css': 'the token file: chart, focus and table colours are written here once so no component holds a hex',
  },
  'animate-pulse': {},
  'animate-spin': {
    'components/ui/icons.tsx': 'the one spinner icon, a true loading state that only shows after a 200 ms wait (useSpinnerVisible)',
  },
};

function allowed(rule: string, name: string): boolean {
  return Object.keys(ALLOW[rule] ?? {}).some((k) => name === k);
}

interface Hit { file: string; line: number; text: string }

function scan(rule: string, test: (line: string, name: string) => boolean): Hit[] {
  const hits: Hit[] = [];
  for (const f of FILES) {
    if (allowed(rule, f.name)) continue;
    f.lines.forEach((text, i) => {
      // a comment explains a rule and may name the thing it forbids
      if (/^\s*(\/\/|\/\*|\*)/.test(text)) return;
      if (test(text, f.name)) hits.push({ file: f.name, line: i + 1, text: text.trim().slice(0, 120) });
    });
  }
  return hits;
}

function report(hits: Hit[]): string {
  return hits.map((h) => `${h.file}:${h.line}  ${h.text}`).join('\n');
}

test('no text under 13 px', () => {
  const hits = scan('small-text', (l) => {
    if (/(?<![\w-])text-xs\b/.test(l)) return true;
    for (const m of l.matchAll(/text-\[([\d.]+)(px|rem)\]/g)) {
      const px = m[2] === 'rem' ? Number(m[1]) * 16 : Number(m[1]);
      if (px < 13) return true;
    }
    for (const m of l.matchAll(/fontSize[:=]\s*\{?\s*(\d+)/g)) if (Number(m[1]) < 13) return true;
    for (const m of l.matchAll(/font-size:\s*([\d.]+)(px|rem)/g)) {
      const px = m[2] === 'rem' ? Number(m[1]) * 16 : Number(m[1]);
      if (px < 13) return true;
    }
    return false;
  });
  assert.equal(hits.length, 0, `text under 13 px:\n${report(hits)}`);
});

test('no transition-all and no transition without named properties', () => {
  // transition-colors, transition-opacity and transition-[grid-template-rows] name their properties. The bare class
  // "transition" and "transition-all" do not.
  const hits = scan('transition', (l) => /(?<![\w-])transition-all(?![\w-])|(?<![\w.\-:])transition(?![\w-])(?!\s*:)/.test(l));
  assert.equal(hits.length, 0, `transition without named properties:\n${report(hits)}`);
});

test('no monospace on a heading, a label, a date or a table header', () => {
  const hits = scan('mono-on-label', (l, name) => {
    if (name.endsWith('.css')) return /\.label-mono/.test(l);
    if (/label-mono/.test(l)) return true;
    // an opening tag of a heading, label, date or header that also carries a mono class
    for (const m of l.matchAll(/<(h[1-6]|th|time|dt|label|legend)\b[^>]*>/g)) {
      if (/font-mono|(?<![\w-])num(?![\w-])/.test(m[0])) return true;
    }
    return false;
  });
  assert.equal(hits.length, 0, `monospace where it does not belong:\n${report(hits)}`);
});

test('no uppercase eyebrow labels', () => {
  const hits = scan('uppercase', (l) => /(?<![\w-])uppercase(?![\w-])|text-transform:\s*uppercase/.test(l));
  assert.equal(hits.length, 0, `uppercase text:\n${report(hits)}`);
});

test('no gradients, glows, blurs or glass', () => {
  const hits = scan('gradient', (l) => /gradient|(?<![\w-])blur(-|\b)|backdrop-|drop-shadow|bg-grid|bp-grid/.test(l));
  assert.equal(hits.length, 0, `decoration:\n${report(hits)}`);
});

test('nothing pings and pulse is only on the allow-list', () => {
  const ping = scan('animate-ping', (l) => /animate-ping/.test(l));
  assert.equal(ping.length, 0, `animate-ping:\n${report(ping)}`);
  const pulse = scan('animate-pulse', (l) => /animate-pulse/.test(l));
  assert.equal(pulse.length, 0, `animate-pulse:\n${report(pulse)}`);
  const spin = scan('animate-spin', (l) => /animate-spin/.test(l));
  assert.equal(spin.length, 0, `animate-spin outside the spinner:\n${report(spin)}`);
});

test('no arrow character glued to link text', () => {
  const hits = scan('arrow', (l) => /[→←↗↘↑↓⟶]|&rarr;|&larr;/.test(l));
  assert.equal(hits.length, 0, `arrow character:\n${report(hits)}`);
});

test('no hex colour outside the token files', () => {
  const hits = scan('hex-colour', (l) => /#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b/.test(l.replace(/href=["']#[^"']*["']/g, '')));
  assert.equal(hits.length, 0, `hex colour:\n${report(hits)}`);
});

test('no date or time formatted without a locale', () => {
  const hits = scan('locale', (l) => /toLocale(Date|Time)?String\(\s*\)/.test(l));
  assert.equal(hits.length, 0, `toLocale...String() without a locale:\n${report(hits)}`);
});

// the legal pages are Markdown, so the scan above does not see them. The same text rules apply: no arrow character glued to
// link text, no raw colour and no em or en dash. content/legal/services.ts holds the optional-service switches.
test('the legal Markdown and the content components follow the text rules', () => {
  const dir = join(ROOT, 'content', 'legal');
  const hits: Hit[] = [];
  for (const name of readdirSync(dir).filter((n) => /\.(md|ts)$/.test(n))) {
    readFileSync(join(dir, name), 'utf8').split('\n').forEach((text, i) => {
      if (/[→←↗↘]|&rarr;|&larr;|[\u2013\u2014]|#[0-9a-fA-F]{6}\b/.test(text)) hits.push({ file: `content/legal/${name}`, line: i + 1, text: text.trim().slice(0, 120) });
    });
  }
  assert.equal(hits.length, 0, `legal text:\n${report(hits)}`);
  // components/content is under components/, so every rule above already covers the content components
  assert.ok(FILES.some((f) => f.name.startsWith('components/content/')), 'components/content is scanned');
});

test('every allow-list entry names a file that still exists', () => {
  const names = new Set(FILES.map((f) => f.name));
  for (const [rule, entries] of Object.entries(ALLOW)) {
    for (const file of Object.keys(entries)) assert.ok(names.has(file), `${rule}: ${file} no longer exists, remove its exception`);
  }
});
