'use client';

import Link from 'next/link';
import Button from '@/components/ui/Button';

// one primary action and a plain link. A visitor cannot make an account (people are invited), so the main button leads to the
// docs and the plain link to the sample dashboard below. The sign-in button lives in the header, once.
export default function HeroActions() {
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
      <Button href="/docs">Read the docs</Button>
      <Link href="#preview-title" className="inline-flex min-h-[44px] items-center text-brand-800 underline underline-offset-2 hover:no-underline dark:text-brand-400">
        See the dashboard
      </Link>
    </div>
  );
}
