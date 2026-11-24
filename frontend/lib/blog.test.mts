// run with `npm test`, which uses the Node test runner with type stripping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parsePost, sortPosts, stripTitleHeading } from './blog.ts';

const file = `---
title: "A title"
date: "2026-05-01"
slug: "ignored"
excerpt: "One sentence."
---

# A title

First paragraph.
`;

test('front matter is read and the slug comes from the file name', () => {
  const post = parsePost('from-file', file);
  assert.equal(post?.slug, 'from-file');
  assert.equal(post?.title, 'A title');
  assert.equal(post?.date, '2026-05-01');
  assert.equal(post?.excerpt, 'One sentence.');
});

test('the heading that repeats the title is dropped from the body', () => {
  assert.equal(parsePost('x', file)?.body, 'First paragraph.');
  assert.equal(stripTitleHeading('# Other\n\ntext', 'A title'), '# Other\n\ntext');
  assert.equal(stripTitleHeading('No heading', 'A title'), 'No heading');
});

test('a file without a title or a real date is not a post', () => {
  assert.equal(parsePost('x', 'no front matter'), null);
  assert.equal(parsePost('x', '---\ndate: "2026-05-01"\n---\nbody'), null);
  assert.equal(parsePost('x', '---\ntitle: "T"\ndate: "yesterday"\n---\nbody'), null);
  assert.equal(parsePost('x', '---\ntitle: "T"\ndate: "2026-13-45"\n---\nbody'), null);
});

test('a file whose name is not a plain slug is not a post', () => {
  const file = '---\ntitle: "T"\ndate: "2026-05-01"\n---\nbody';
  assert.ok(parsePost('a-plain-slug', file));
  for (const slug of ['javascript:alert(1)', '../x', 'Upper', 'a b', '"onmouseover', 'a--b', '-a', '']) {
    assert.equal(parsePost(slug, file), null, slug);
  }
});

test('posts sort newest first', () => {
  assert.deepEqual(sortPosts([{ date: '2026-05-01' }, { date: '2026-05-28' }, { date: '2026-05-15' }]).map((p) => p.date), ['2026-05-28', '2026-05-15', '2026-05-01']);
});
