import { notFound } from 'next/navigation';
import { readFileSync, readdirSync } from 'fs';
import { join } from 'path';
import type { Metadata } from 'next';
import Link from 'next/link';
import ReactMarkdown from 'react-markdown';

const CONTENT_DIR = join(process.cwd(), 'content', 'blog');

interface FrontMatter {
  title: string;
  date: string;
  slug: string;
  excerpt: string;
}

function parseFrontMatter(raw: string): { meta: FrontMatter; body: string } {
  const match = raw.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
  if (!match) return { meta: { title: '', date: '', slug: '', excerpt: '' }, body: raw };
  const meta: Partial<FrontMatter> = {};
  for (const line of match[1].split('\n')) {
    const sep = line.indexOf(':');
    if (sep === -1) continue;
    const key = line.slice(0, sep).trim() as keyof FrontMatter;
    meta[key] = line.slice(sep + 1).trim().replace(/^"|"$/g, '');
  }
  return { meta: meta as FrontMatter, body: match[2].trim() };
}

function getPost(slug: string) {
  const filePath = join(CONTENT_DIR, `${slug}.md`);
  try {
    const raw = readFileSync(filePath, 'utf8');
    return parseFrontMatter(raw);
  } catch {
    return null;
  }
}

export async function generateStaticParams() {
  try {
    return readdirSync(CONTENT_DIR)
      .filter((f) => f.endsWith('.md'))
      .map((f) => ({ slug: f.replace('.md', '') }));
  } catch {
    return [];
  }
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const post = getPost(slug);
  if (!post) return { title: 'Post not found - PHAEMOS' };
  return {
    title: `${post.meta.title} - PHAEMOS Blog`,
    description: post.meta.excerpt,
  };
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
}

export default async function BlogPostPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const post = getPost(slug);
  if (!post) notFound();
  const { meta, body } = post;

  return (
    <main className="p-6 max-w-3xl mx-auto">

      <div className="mb-8 space-y-2">
        <Link href="/blog" className="text-sm text-brand-600 dark:text-brand-400 hover:underline">
          &larr; Back to blog
        </Link>
        <p className="text-xs text-surface-400 dark:text-surface-500 font-mono pt-2">
          {formatDate(meta.date)}
        </p>
        <h1 className="text-2xl font-bold tracking-tight text-surface-900 dark:text-surface-50">
          {meta.title}
        </h1>
        <p className="text-surface-600 dark:text-surface-400">{meta.excerpt}</p>
      </div>

      <article className="card p-8 prose prose-sm max-w-none dark:prose-invert
        prose-headings:text-surface-900 dark:prose-headings:text-surface-50
        prose-headings:font-bold prose-headings:tracking-tight
        prose-p:text-surface-600 dark:prose-p:text-surface-400
        prose-p:leading-relaxed
        prose-a:text-brand-600 dark:prose-a:text-brand-400 prose-a:no-underline hover:prose-a:underline
        prose-strong:text-surface-900 dark:prose-strong:text-surface-50
        prose-code:font-mono prose-code:text-sm
        prose-code:bg-surface-100 dark:prose-code:bg-surface-800
        prose-code:px-1 prose-code:rounded
        prose-pre:bg-surface-900 dark:prose-pre:bg-surface-800
        prose-pre:rounded-xl prose-pre:border prose-pre:border-surface-200 dark:prose-pre:border-surface-700
        prose-li:text-surface-600 dark:prose-li:text-surface-400
        prose-hr:border-surface-200 dark:prose-hr:border-surface-800"
      >
        <ReactMarkdown>{body}</ReactMarkdown>
      </article>

    </main>
  );
}
