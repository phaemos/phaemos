import type { Metadata } from 'next';
import PageShell from '@/components/content/PageShell';
import Prose from '@/components/content/Prose';
import TextLink from '@/components/content/TextLink';
import ContactForm from '@/components/ContactForm';
import { ISSUES_URL } from '@/components/content/legal';

export const metadata: Metadata = {
  title: 'Contact',
  description: 'Send us a question or feedback.',
};

export default function ContactPage() {
  return (
    <PageShell
      title="Contact"
      lead={
        <>
          For questions and feedback. Bugs and feature requests go in a <TextLink href={ISSUES_URL}>GitHub issue</TextLink>, where everyone can follow them.
        </>
      }
    >
      <ContactForm />

      <Prose className="mt-10 border-t border-surface-200 pt-6 text-base dark:border-surface-800">
        <p>
          Security issues: do not use this form. Follow the <TextLink href="/security">security policy</TextLink>.
        </p>
        <p>
          Help using PHAEMOS: see <TextLink href="/support">support</TextLink> or email <TextLink href="mailto:support@phaemos.com">support@phaemos.com</TextLink>.
        </p>
      </Prose>
    </PageShell>
  );
}
