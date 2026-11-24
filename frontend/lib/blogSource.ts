import { readdirSync, readFileSync } from 'fs';
import { join } from 'path';
import { parsePost, sortPosts, type Post } from './blog';

const CONTENT_DIR = join(process.cwd(), 'content', 'blog');

// every post in content/blog, newest first. The index, the post pages and their static paths all read this, so a
// new file appears everywhere at once and a malformed one appears nowhere.
export function loadPosts(): Post[] {
  let files: string[];
  try {
    files = readdirSync(CONTENT_DIR).filter((f) => f.endsWith('.md'));
  } catch {
    return [];
  }
  const posts: Post[] = [];
  for (const file of files) {
    const post = parsePost(file.replace(/\.md$/, ''), readFileSync(join(CONTENT_DIR, file), 'utf8'));
    if (post) posts.push(post);
  }
  return sortPosts(posts);
}

export function getPost(slug: string): Post | null {
  return loadPosts().find((p) => p.slug === slug) ?? null;
}
