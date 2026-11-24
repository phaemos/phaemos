import type { Metadata } from 'next';
import PageShell from '@/components/content/PageShell';
import Prose, { Code } from '@/components/content/Prose';
import TextLink from '@/components/content/TextLink';
import StatusCheck from '@/components/content/StatusCheck';
import { DISCUSSIONS_URL } from '@/components/content/legal';

export const metadata: Metadata = {
  title: 'Status',
  description: 'Whether the PHAEMOS API, database and cache answer right now.',
};

// the page is static and the check is a small client component, so the heading and the notes exist without script
export default function StatusPage() {
  return (
    <PageShell
      title="Status"
      lead="Whether the API, the database and the cache answer right now."
    >
      <StatusCheck />

      <Prose className="mt-10 text-base text-surface-600 dark:text-surface-400">
        <p>
          This page asks the API&apos;s <Code>/status</Code> route from your browser every 30 seconds. The API replies after one test query to the database and one ping to the cache. It does not check the sensor nodes or whether readings are arriving.
        </p>
        <p>
          Incidents are announced in <TextLink href={DISCUSSIONS_URL}>GitHub Discussions</TextLink>. If you see a problem this page does not, email <TextLink href="mailto:support@phaemos.com">support@phaemos.com</TextLink>.
        </p>
      </Prose>
    </PageShell>
  );
}
