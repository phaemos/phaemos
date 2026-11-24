'use client';

import Link from 'next/link';
import { useSyncExternalStore } from 'react';
import SiteHeading from '@/components/ui/SiteHeading';
import { LinkButton } from '@/components/ui/Button';
import { readContactSent } from '@/lib/contactSent';

const noop = () => () => {};

// says the message arrived only when this tab really sent one. Opened any other way, it says so plainly instead of
// thanking someone for a message that never left.
export default function ContactSent() {
  // the server cannot read the tab's storage, so it renders the neutral text and the browser settles it
  const sent = useSyncExternalStore(noop, () => readContactSent(), () => false);

  return (
    <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6 md:py-16">
      {sent ? (
        <SiteHeading
          title="Message sent"
          lead="Thank you. Your message reached our mailbox and we will reply to the email address you gave. Bugs and feature requests are easier for everyone to follow as a GitHub issue."
        />
      ) : (
        <SiteHeading title="No message sent from this page" lead="This page confirms a message sent with the contact form. Nothing was sent from this tab in the last ten minutes." />
      )}
      <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-2">
        <LinkButton href="/">Go to the home page</LinkButton>
        <Link href="/contact" className="inline-flex min-h-[44px] items-center text-brand-800 underline underline-offset-2 hover:no-underline dark:text-brand-400">
          {sent ? 'Send another message' : 'Open the contact form'}
        </Link>
      </div>
    </div>
  );
}
