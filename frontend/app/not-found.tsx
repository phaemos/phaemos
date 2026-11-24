import type { Metadata } from 'next';
import Link from 'next/link';
import Logo from '@/components/ui/Logo';
import { siteHref } from '@/lib/links';
import { LinkButton } from '@/components/ui/Button';

export const metadata: Metadata = { title: 'Page not found' };

// the root layout has no shell, so this page brings its own landmark. A wrong address under a signed-in route sends a
// signed-out visitor to the login page first, which is the proxy doing its job.
export default function NotFound() {
  return (
    <main id="main" className="mx-auto flex min-h-[calc(100dvh-var(--cookie-banner-height,0px))] max-w-xl flex-col justify-center px-4 py-16 sm:px-6">
      <Link href={siteHref('/')} className="mb-10 inline-flex min-h-[44px] items-center gap-2.5 no-underline" aria-label="PHAEMOS home">
        <Logo />
      </Link>
      <h1 className="text-4xl font-semibold tracking-[-0.02em] text-surface-900 dark:text-surface-50">Page not found</h1>
      <p className="mt-4 text-surface-700 dark:text-surface-300">
        There is no page at this address. It may have moved or the link may be mistyped.
      </p>
      <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-2">
        <LinkButton href={siteHref('/')}>Go to the home page</LinkButton>
        <Link href={siteHref('/docs')} className="inline-flex min-h-[44px] items-center text-brand-800 underline underline-offset-2 hover:no-underline dark:text-brand-400">
          Read the docs
        </Link>
      </div>
    </main>
  );
}
