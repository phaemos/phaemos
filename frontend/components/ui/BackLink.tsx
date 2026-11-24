import Link from 'next/link';

// "Back to machines" above the h1 of a nested page (a machine, a release). The page renders it, the shell does not;
// it is a real link with a 44 px target. The word "Back to" tells where it goes, so it needs no arrow icon.
export default function BackLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="-ml-1 inline-flex min-h-[44px] items-center rounded-md px-1 text-base text-brand-800 underline underline-offset-2 hover:no-underline dark:text-brand-400">
      Back to {children}
    </Link>
  );
}
