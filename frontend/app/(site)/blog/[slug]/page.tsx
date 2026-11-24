import { notFound } from 'next/navigation';
import type { Metadata } from 'next';
import ReactMarkdown from 'react-markdown';
import Breadcrumbs from '@/components/content/Breadcrumbs';
import SiteHeading from '@/components/ui/SiteHeading';
import { getPost, loadPosts } from '@/lib/blogSource';
import { formatDate } from '@/lib/format';
import Time from '@/components/ui/Time';

export function generateStaticParams() {
  return loadPosts().map((p) => ({ slug: p.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const post = getPost(slug);
  if (!post) return { title: 'Post not found' };
  return { title: post.title, description: post.excerpt || undefined };
}

export default async function BlogPostPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const post = getPost(slug);
  if (!post) notFound();

  return (
    <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6 md:py-16">
      <Breadcrumbs trail={[{ name: 'Blog', href: '/blog' }]} current={post.title} />
      <SiteHeading title={post.title} className="mt-4" />
      <p className="mt-4 text-base text-surface-700 dark:text-surface-400">
        <Time value={post.date} format="date" />
      </p>

      <article
        className="prose mt-10 max-w-[72ch] dark:prose-invert
          prose-headings:font-semibold prose-headings:tracking-tight prose-headings:text-surface-900 dark:prose-headings:text-surface-50
          prose-p:text-surface-700 dark:prose-p:text-surface-300
          prose-li:text-surface-700 dark:prose-li:text-surface-300
          prose-a:text-brand-800 dark:prose-a:text-brand-400
          prose-strong:text-surface-900 dark:prose-strong:text-surface-50
          prose-code:rounded prose-code:bg-surface-100 prose-code:px-1 prose-code:font-mono prose-code:text-base prose-code:before:content-none prose-code:after:content-none dark:prose-code:bg-surface-800
          prose-pre:rounded-lg prose-pre:border prose-pre:border-surface-200 prose-pre:bg-surface-100 prose-pre:text-surface-900 dark:prose-pre:border-surface-800 dark:prose-pre:bg-surface-900 dark:prose-pre:text-surface-50
          prose-hr:border-surface-200 dark:prose-hr:border-surface-800"
      >
        {/* the page's h1 is the title above, so any h1 left in a body drops to an h2 */}
        <ReactMarkdown components={{ h1: ({ node: _node, ...props }) => <h2 {...props} /> }}>{post.body}</ReactMarkdown>
      </article>
    </div>
  );
}
