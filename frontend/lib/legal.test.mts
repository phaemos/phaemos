// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { applyConditions, evaluate, headings, markPlaceholders, parseLegal, scanPlaceholders, slugify, splitBlocks } from './legal.ts';
import { SERVICES } from '../content/legal/services.ts';

const on = { brevo: true, google: false, github: true };
const off = { brevo: false, google: false, github: false };

test('a condition names keys, negates and accepts any of several', () => {
  assert.equal(evaluate('brevo', on), true);
  assert.equal(evaluate('not brevo', on), false);
  assert.equal(evaluate('google|github', on), true);
  assert.equal(evaluate('google|github', off), false);
  assert.equal(evaluate('not google|github', off), true);
});

test('an unknown service is an error and never a quiet hide', () => {
  assert.throws(() => evaluate('brevoo', on), /unknown service/);
});

test('a block shows only while its service is on', () => {
  const text = 'before\n:::if brevo\ninside\n:::\nafter';
  assert.equal(applyConditions(text, on), 'before\ninside\nafter');
  assert.equal(applyConditions(text, off), 'before\nafter');
});

test('blocks nest and a block that is never closed is an error', () => {
  const text = ':::if brevo\na\n:::if github\nb\n:::\nc\n:::';
  assert.equal(applyConditions(text, on), 'a\nb\nc');
  assert.equal(applyConditions(text, { brevo: true, github: false }), 'a\nc');
  assert.throws(() => applyConditions(':::if brevo\nx', on), /never closed/);
  assert.throws(() => applyConditions('x\n:::', on), /never opened/);
});

test('a line ending in a marker is kept or dropped as a whole', () => {
  const text = '| a | b | {if brevo}\n| c | d |';
  assert.equal(applyConditions(text, on), '| a | b |\n| c | d |');
  assert.equal(applyConditions(text, off), '| c | d |');
});

test('words inside a sentence follow the service', () => {
  const text = 'An email{if brevo: or text} is sent. {if not brevo:Nothing else is.}';
  assert.equal(applyConditions(text, on), 'An email or text is sent. ');
  assert.equal(applyConditions(text, off), 'An email is sent. Nothing else is.');
});

test('placeholders are found with their line and whether their passage is visible', () => {
  const raw = ['a [PUBLICATION DATE] b', ':::if brevo', 'c [BREVO PROCESSING LOCATION]', ':::', 'd [contact](mailto:x) [WORD](https://x)', 'e {if brevo:[HIDDEN]}'].join('\n');
  assert.deepEqual(scanPlaceholders(raw, off), [{ name: 'PUBLICATION DATE', line: 1, active: true }, { name: 'BREVO PROCESSING LOCATION', line: 3, active: false }]);
  assert.equal(scanPlaceholders(raw, on).filter((h) => h.active).length, 3);
});

test('a placeholder is shown as a marked link and never as a raw bracket', () => {
  assert.equal(markPlaceholders('x [LEGAL NAME] y'), 'x [to be completed before publication](#placeholder "legal name") y');
  assert.equal(markPlaceholders('[a link](https://x)'), '[a link](https://x)');
});

test('front matter is read and a file without a title is not a page', () => {
  const raw = '---\ntitle: "T"\ndescription: "D."\nversion: "2026-11-22"\n---\n\nBody\n\n## One\n\n```\n## not a heading\n```\n\n## Two words\n';
  const doc = parseLegal('t', raw, off);
  assert.equal(doc?.title, 'T');
  assert.equal(doc?.versionLabel, 'Version date');
  assert.deepEqual(doc?.toc, [{ id: 'one', text: 'One' }, { id: 'two-words', text: 'Two words' }]);
  assert.equal(parseLegal('t', '---\ndescription: "D"\nversion: "x"\n---\nb', off), null);
  assert.equal(parseLegal('t', 'no front matter', off), null);
});

test('headings get stable anchors', () => {
  assert.equal(slugify('1. Who we are'), '1-who-we-are');
  assert.deepEqual(headings('## A\ntext\n### Not\n## B'), [{ id: 'a', text: 'A' }, { id: 'b', text: 'B' }]);
});

test('a table is split from prose into head and rows', () => {
  const blocks = splitBlocks('intro\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |\n\nafter');
  assert.equal(blocks.length, 3);
  assert.deepEqual(blocks[1], { kind: 'table', head: ['A', 'B'], rows: [['1', '2'], ['3', '4']] });
});

// the real files: every page parses with the real service list and every marker names a real service
test('every legal file parses with each service on and off and keeps its headings in order', () => {
  const dir = new URL('../content/legal/', import.meta.url);
  const all = Object.fromEntries(Object.keys(SERVICES).map((k) => [k, true]));
  const none = Object.fromEntries(Object.keys(SERVICES).map((k) => [k, false]));
  for (const name of readdirSync(dir).filter((f) => f.endsWith('.md'))) {
    const raw = readFileSync(new URL(name, dir), 'utf8');
    for (const services of [all, none]) {
      const doc = parseLegal(name, raw, services);
      assert.ok(doc, `${name} is a page`);
      assert.ok(doc.toc.length > 1, `${name} has a contents list`);
      assert.ok(!/^#\s/m.test(doc.body), `${name} has an h1 in its body: the page supplies the h1`);
      assert.ok(!/:::|\{if /.test(doc.body), `${name} still has a marker after the conditions are applied`);
    }
  }
});

import { badVersionLine, isIsoDay, joinWords, tokensFor, PLACEHOLDER, isDraft } from './legal.ts';
import { hostOf, isSplit } from '../content/legal/services.ts';
import { parseSplitConfig } from './publicPaths.ts';

test('a version is a real calendar day', () => {
  assert.equal(isIsoDay('2026-11-22'), true);
  assert.equal(isIsoDay('2026-02-31'), false);
  assert.equal(isIsoDay('22 November 2026'), false);
  assert.equal(isIsoDay('TBC'), false);
  assert.equal(isIsoDay('2026-13-01'), false);
});

test('any bracketed words that are not a link are a placeholder', () => {
  const found = (text: string) => [...text.matchAll(PLACEHOLDER)].map((m) => m[1]);
  assert.deepEqual(found('a [ADDRESS LINE 2] b [Company name] c [NAME & ADDRESS] d [X] e'), ['ADDRESS LINE 2', 'Company name', 'NAME & ADDRESS', 'X']);
  assert.deepEqual(found('see [the notice](/privacy) and [mail](mailto:a@b.c)'), []);
});

test('a version that is not a real day is reported with its line', () => {
  const page = (v: string) => `---\ntitle: "T"\ndescription: "D"\nversion: "${v}"\n---\nbody`;
  assert.equal(badVersionLine(page('22 November 2026')), 4);
  assert.equal(badVersionLine(page('2026-02-31')), 4);
  assert.equal(badVersionLine(page('2026-11-22')), null);
  // a bracketed placeholder is found by the placeholder scan and not counted twice
  assert.equal(badVersionLine(page('[PUBLICATION DATE]')), null);
});

test('a draft is a page with a placeholder or a version that is not a day', () => {
  const doc = (version: string, body: string) => ({ slug: 'x', title: 't', description: 'd', version, versionLabel: 'v', body, toc: [] });
  assert.equal(isDraft(doc('2026-11-22', 'all done')), false);
  assert.equal(isDraft(doc('2026-11-22', 'name [LEGAL NAME]')), true);
  assert.equal(isDraft(doc('soon', 'all done')), true);
});

test('lists have no comma before the last word', () => {
  assert.equal(joinWords([]), '');
  assert.equal(joinWords(['Google']), 'Google');
  assert.equal(joinWords(['Google', 'GitHub']), 'Google or GitHub');
  assert.equal(joinWords(['Google', 'GitHub', 'Microsoft']), 'Google, GitHub or Microsoft');
  assert.equal(joinWords(['A', 'B', 'C'], 'and'), 'A, B and C');
});

test('a provider is named only while it is switched on', () => {
  const t = (s: Record<string, boolean>) => tokensFor(s);
  assert.equal(t({ google: false, github: false, microsoft: false }).providers, '');
  assert.equal(t({ google: false, github: true, microsoft: false }).providers, 'GitHub');
  assert.equal(t({ google: true, github: true, microsoft: true }).providers, 'Google, GitHub or Microsoft');
  // with every service off the data-bridge list names no optional service
  const off = t({ analytics: false, google: false, github: false, microsoft: false }).transferrers;
  assert.ok(!/Google|Microsoft/.test(off), off);
  assert.ok(/Google/.test(t({ analytics: true }).transferrers));
});

test('with every service off no page names an optional service', () => {
  const dir = new URL('../content/legal/', import.meta.url);
  const none = Object.fromEntries(Object.keys(SERVICES).map((k) => [k, false]));
  for (const name of readdirSync(dir).filter((f) => f.endsWith('.md'))) {
    const doc = parseLegal(name, readFileSync(new URL(name, dir), 'utf8'), none);
    assert.ok(doc);
    // GitHub is named as the host of the code and the advisories. Google, Microsoft, Brevo and the analytics cookie names are optional.
    // Google Workspace hosts the mailboxes whatever is switched on, so that one name is always in the privacy notice
    const body = doc.body.replace(/Google \(Workspace\)|Google Workspace/g, '');
    for (const word of ['Google', 'Microsoft', 'Brevo', 'Discord', '_ga']) assert.ok(!body.includes(word), `${name} names ${word} with every service off`);
  }
});

// the host names a text mentions, so a check compares whole names and not a piece of a longer one
function namesHost(text: string, host: string): boolean {
  const names = text.toLowerCase().match(/[a-z0-9-]+(?:\.[a-z0-9-]+)+/g) ?? [];
  return names.some((name) => name === host || name.endsWith(`.${host}`));
}

test('single and two-address wording both read true', () => {
  const dir = new URL('../content/legal/', import.meta.url);
  const base = Object.fromEntries(Object.keys(SERVICES).map((k) => [k, false]));
  const two = { site: 'phaemos.com', app: 'dashboard.phaemos.com', api: 'api.phaemos.com' };
  const one = { site: 'phaemos.com', app: 'phaemos.com', api: 'api.phaemos.com' };
  const cookies = readFileSync(new URL('cookies.md', dir), 'utf8');
  const split = parseLegal('cookies', cookies, { ...base, split: true }, two)!.body;
  const single = parseLegal('cookies', cookies, { ...base, split: false }, one)!.body;
  assert.ok(split.includes('dashboard.phaemos.com only') && split.includes('one for each'));
  assert.ok(!namesHost(single, 'dashboard.phaemos.com') && !single.includes('one for each'));
});

test('the legal pages read the two addresses as the app does', () => {
  const cases: [string | undefined, string | undefined][] = [
    [undefined, undefined], ['', ''], ['https://phaemos.com', undefined], [undefined, 'https://dashboard.phaemos.com'],
    ['https://phaemos.com', 'https://dashboard.phaemos.com'], ['https://phaemos.com', 'https://phaemos.com'], ['https://phaemos.com', 'HTTPS://PHAEMOS.COM./'],
    ['https://phaemos.com', 'https://phaemos.com:443'], ['http://phaemos.test:3200', 'http://dashboard.phaemos.test:3200'], ['https://phaemos.com/', 'https://dashboard.phaemos.com/x?y=1'],
    ['not a url', 'https://dashboard.phaemos.com'], ['ftp://phaemos.com', 'https://dashboard.phaemos.com'], ['https://www.phaemos.com', 'https://phaemos.com'],
  ];
  for (const [site, app] of cases) assert.equal(isSplit(site, app), parseSplitConfig(site, app).split, JSON.stringify([site, app]));
  assert.equal(hostOf('https://Phaemos.com:443/x'), 'phaemos.com');
});

test('an indented marker is still a marker and a pipe inside code stays in its cell', () => {
  assert.equal(applyConditions('a\n  :::if brevo\nb\n  :::\nc', { brevo: false }), 'a\nc');
  const t = splitBlocks('| A | B |\n| --- | --- |\n| `x | y` | 2 |')[0];
  assert.deepEqual(t.kind === 'table' ? t.rows[0] : [], ['`x | y`', '2']);
});

test('a line that ends in a marker can also hold an inline passage', () => {
  const text = '| a {if brevo:text} b | c | {if github}';
  assert.equal(applyConditions(text, { brevo: true, github: true }), '| a text b | c |');
  assert.equal(applyConditions(text, { brevo: false, github: true }), '| a  b | c |');
  assert.equal(applyConditions(text, { brevo: true, github: false }), '');
});

// the postal address and the ICO number may wait while the hosted service is closed and must be filled once it opens
test('the postal address and ICO number are only required once the hosted service is open', () => {
  const raw = readFileSync(new URL('../content/legal/privacy.md', import.meta.url), 'utf8');
  const base = Object.fromEntries(Object.keys(SERVICES).map((k) => [k, false]));
  const open = (hosted: boolean) => scanPlaceholders(raw, { ...base, hosted }).filter((h) => h.active).map((h) => h.name);
  for (const name of ['POSTAL ADDRESS OF THE CONTROLLER', 'ICO REGISTRATION NUMBER']) {
    assert.ok(!open(false).includes(name), `${name} counts while the hosted service is closed`);
    assert.ok(open(true).includes(name), `${name} is not required once the hosted service is open`);
  }
});
