import { getPost, loadPosts } from '@/lib/blogSource';
import { OG_SIZE, OG_TYPE, ogImage } from '@/lib/ogImage';

export const size = OG_SIZE;
export const contentType = OG_TYPE;
export const alt = 'A post on the PHAEMOS blog';

// built once per post at build time, like the post itself
export const dynamicParams = false;

export function generateStaticParams() {
  return loadPosts().map((p) => ({ slug: p.slug }));
}

// each post's card carries its own title and excerpt
export default async function Image({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const post = getPost(slug);
  return ogImage(post?.title ?? 'Blog', post?.excerpt || undefined);
}
