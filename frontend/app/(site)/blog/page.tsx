import type { Metadata } from 'next';
import Link from 'next/link';
import PageShell from '@/components/content/PageShell';
import { loadPosts } from '@/lib/blogSource';
import { formatDate } from '@/lib/format';
import Time from '@/components/ui/Time';

export const metadata: Metadata = {
  title: 'Blog',
  description: 'Notes on how PHAEMOS is built: the model, the firmware and the hardware.',
};

// static: the posts are read from content/blog at build time
export default function BlogPage() {
  const posts = loadPosts();

  return (
    <PageShell title="Blog" lead="Notes on how PHAEMOS is built: the model, the firmware and the hardware.">
      {posts.length === 0 ? (
        <p className="max-w-[72ch] text-surface-700 dark:text-surface-300">There are no posts yet.</p>
      ) : (
        <ol className="max-w-3xl divide-y divide-surface-200 border-y border-surface-200 dark:divide-surface-800 dark:border-surface-800">
          {posts.map((post) => (
            <li key={post.slug} className="py-5">
              <Time value={post.date} format="date" className="text-base text-surface-600 dark:text-surface-400" />
              <p className="mt-1">
                <Link
                  href={`/blog/${encodeURIComponent(post.slug)}`}
                  className="inline-flex min-h-[44px] items-center text-lg font-semibold text-surface-900 underline underline-offset-2 hover:no-underline dark:text-surface-50"
                >
                  {post.title}
                </Link>
              </p>
              {post.excerpt && <p className="max-w-[72ch] text-surface-700 dark:text-surface-300">{post.excerpt}</p>}
            </li>
          ))}
        </ol>
      )}
    </PageShell>
  );
}
