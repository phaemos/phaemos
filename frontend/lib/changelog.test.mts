// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { countByKind, firstSentence, hasItems, parseChangelog, stripMarkdown, summarise, versionHref } from './changelog.ts';

const fixture = `# Changelog

Intro text.

---

## [Unreleased]

### Added

- A new thing with \`code\` and a [link](https://example.com/a_b).
- Another item.
  - nested one
  - nested two

## [1.2.0] - 2026-02-03

### Fixed

- First fix. It has a second sentence.

- Separated by a blank line.

### Security

- Patched a flaw.

### Curiosities

Some prose that is not a list.

---

## [1.0.0]

Short note under the heading.

### Added

- Initial.
`;

test('reads releases in order with and without dates', () => {
  const r = parseChangelog(fixture);
  assert.deepEqual(r.map((x) => x.version), ['Unreleased', '1.2.0', '1.0.0']);
  assert.deepEqual(r.map((x) => x.date), [null, '2026-02-03', null]);
  assert.equal(r[0].unreleased, true);
  assert.equal(r[0].slug, 'unreleased');
});

test('keeps inline code, links and nested lists as Markdown', () => {
  const [unreleased] = parseChangelog(fixture);
  const added = unreleased.sections[0];
  assert.equal(added.items.length, 2);
  assert.ok(added.items[0].includes('`code`'));
  assert.ok(added.items[0].includes('[link](https://example.com/a_b)'));
  assert.ok(added.items[1].includes('\n- nested one'));
  assert.ok(added.body.includes('- nested two'));
});

test('counts items by kind and keeps unknown sections and prose', () => {
  const r = parseChangelog(fixture);
  assert.deepEqual(countByKind(r[1]), { fixed: 2, security: 1, other: 1 });
  const other = r[1].sections.find((s) => s.kind === 'other');
  assert.equal(other?.name, 'Curiosities');
  assert.equal(other?.body, 'Some prose that is not a list.');
  assert.equal(r[2].preamble, 'Short note under the heading.');
});

test('drops horizontal rules between releases', () => {
  const r = parseChangelog(fixture);
  assert.ok(!r[1].sections.some((s) => s.body.includes('---')));
});

test('strips Markdown for plain text', () => {
  assert.equal(stripMarkdown('A **bold** `code` and [a link](https://x.y) and _em_.'), 'A bold code and a link and em.');
  for (const md of ['<scr<b></b>ipt>x</script>', '`<`script>x', '[<](u)script>x']) {
    assert.ok(!stripMarkdown(md).includes('<'), md);
  }
});

test('takes the first sentence and skips nested lists', () => {
  assert.equal(firstSentence('Does a thing (issue 12). Then more.\n  - nested'), 'Does a thing (issue 12).');
  assert.equal(firstSentence('No full stop here'), 'No full stop here.');
  assert.equal(firstSentence('Uses e.g. a path. Next.'), 'Uses e.g. a path.');
});

test('summary prefers security, then added then joins two short sentences', () => {
  const r = parseChangelog(fixture);
  assert.equal(summarise(r[1]), 'Patched a flaw.');
  assert.equal(summarise(r[0]), 'A new thing with code and a link. Another item.');
});

test('a paragraph under the heading is the summary and a filter still uses its section', () => {
  const r = parseChangelog(fixture);
  assert.equal(summarise(r[2]), 'Short note under the heading.');
  assert.equal(summarise(r[2], 'added'), 'Initial.');
});

test('with no paragraph the derived summary is used', () => {
  const [r] = parseChangelog('## [1.0.0] - 2026-01-01\n\n### Fixed\n\n- Fixed it. More.\n');
  assert.equal(summarise(r), 'Fixed it.');
});

test('summary falls back to one sentence over the limit and never cuts a word', () => {
  const long = `## [1.0.0] - 2026-01-01\n\n### Added\n\n- ${'Alpha beta. '.repeat(1).trim()}\n- ${'word '.repeat(60).trim()}.\n`;
  const [r] = parseChangelog(long);
  assert.equal(summarise(r), 'Alpha beta.');
  const single = `## [1.0.0] - 2026-01-01\n\n### Added\n\n- ${'word '.repeat(60).trim()}.\n`;
  const out = summarise(parseChangelog(single)[0]);
  assert.ok(out.length <= 184);
  assert.ok(out.endsWith('word…'));
});

test('encodes a version in a link', () => {
  const [r] = parseChangelog('## [1.0.0-rc.1+build 5] - 2026-01-01\n\n### Added\n\n- x\n');
  assert.equal(versionHref(r), '/changelog/1.0.0-rc.1%2Bbuild%205');
});

test('handles CRLF line endings', () => {
  const r = parseChangelog('## [1.0.0] - 2026-01-01\r\n\r\n### Added\r\n\r\n- one\r\n');
  assert.equal(r[0].sections[0].items[0], 'one');
});

test('the real CHANGELOG.md: every release heading became a release, in order', () => {
  const file = readFileSync(fileURLToPath(new URL('../../CHANGELOG.md', import.meta.url)), 'utf8');
  const headings = [...file.matchAll(/^## \[([^\]]+)\]/gm)].map((m) => m[1]);
  const releases = parseChangelog(file);
  assert.ok(headings.length > 5);
  assert.deepEqual(releases.map((r) => r.version), headings);
  for (const r of releases) {
    assert.ok(hasItems(r), `release ${r.version} is empty`);
    assert.ok(summarise(r).length > 0, `release ${r.version} has no summary`);
    assert.ok(r.preamble.length > 0, `release ${r.version} has no written summary`);
  }
  // every list item in the file landed in some release
  const bullets = file.split('\n').filter((l) => /^[-*+] /.test(l)).length;
  const parsed = releases.flatMap((r) => r.sections).reduce((n, s) => n + s.items.length, 0);
  assert.equal(parsed, bullets);
});
