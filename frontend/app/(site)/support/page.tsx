import type { Metadata } from 'next';
import PageShell from '@/components/content/PageShell';
import Section from '@/components/content/Section';
import Prose, { Code, CodeBlock } from '@/components/content/Prose';
import TextLink from '@/components/content/TextLink';
import { DISCUSSIONS_URL, ISSUES_URL } from '@/components/content/legal';

export const metadata: Metadata = {
  title: 'Support',
  description: 'Where to ask a question, report a bug and fix the common setup problems.',
};

// the routes and the problems below are the ones in SUPPORT.md at the root of the repository
const ROUTES: { name: string; body: React.ReactNode }[] = [
  {
    name: 'Questions and ideas',
    body: (
      <>
        Start a thread in <TextLink href={DISCUSSIONS_URL}>GitHub Discussions</TextLink>. It is the main help channel for setup questions, usage questions and feature ideas. The answers stay searchable.
      </>
    ),
  },
  {
    name: 'Bugs',
    body: (
      <>
        Open an issue on <TextLink href={ISSUES_URL}>GitHub</TextLink> with the bug report template and the steps to reproduce it.
      </>
    ),
  },
  {
    name: 'Security problems',
    body: (
      <>
        Do not open a public issue. Follow the <TextLink href="/security">security policy</TextLink>.
      </>
    ),
  },
  {
    name: 'Platform status',
    body: (
      <>
        The <TextLink href="/status">status page</TextLink> shows whether the API, the database and the cache answer. Outages and incidents are announced in GitHub Discussions.
      </>
    ),
  },
  {
    name: 'Email',
    body: (
      <>
        <TextLink href="mailto:support@phaemos.com">support@phaemos.com</TextLink> for help using PHAEMOS and <TextLink href="mailto:contact@phaemos.com">contact@phaemos.com</TextLink> for anything else. There is also a <TextLink href="/contact">contact form</TextLink>.
      </>
    ),
  },
  {
    name: 'Chat',
    body: <>A community Discord server is planned. Until it opens, GitHub Discussions is the place to talk.</>,
  },
];

const PROBLEMS: { problem: React.ReactNode; fix: React.ReactNode }[] = [
  {
    problem: <>The database is empty after <Code>docker compose down -v</Code></>,
    fix: (
      <>
        The <Code>-v</Code> flag deletes the database volume. A plain <Code>docker compose down</Code> or <Code>docker compose stop</Code> keeps it. After a wipe run <Code>make migrate</Code> again.
      </>
    ),
  },
  {
    problem: <>Sign-in is blocked after failed attempts</>,
    fix: <>Five wrong passwords or wrong authentication codes make the place you sign in from wait 30 seconds and the wait doubles up to 15 minutes. The account itself is never locked. Wait or sign in from a browser you have used before.</>,
  },
  {
    problem: <>The sign-in form says too many requests</>,
    fix: <>Sign-in is limited to 5 requests a minute for each IP address. Wait a minute and try again. People behind one shared address share the limit.</>,
  },
  {
    problem: <>The dashboard shows a blank screen</>,
    fix: (
      <>
        Check that <Code>frontend/.env.local</Code> contains the line below, then restart the dashboard.
        <CodeBlock label="The line to put in frontend/.env.local">{'NEXT_PUBLIC_API_URL=http://localhost:8000'}</CodeBlock>
      </>
    ),
  },
  {
    problem: <>The contact form does not send</>,
    fix: (
      <>
        Check that <Code>RESEND_API_KEY</Code> and <Code>FROM_EMAIL</Code> are set for the API and that the sending domain is verified in Resend. Outside development the API answers 503 when the key is missing or Resend refuses the message. In development with no key it logs the message instead.
      </>
    ),
  },
];

export default function SupportPage() {
  return (
    <PageShell
      title="Support"
      lead="Where to ask a question, report a bug and fix the common setup problems."
    >
      <Section id="help" title="Getting help">
        <dl className="max-w-3xl divide-y divide-surface-200 border-y border-surface-200 dark:divide-surface-800 dark:border-surface-800">
          {ROUTES.map(({ name, body }) => (
            <div key={name} className="grid gap-x-6 py-3 sm:grid-cols-[12rem_1fr]">
              <dt className="font-medium text-surface-900 dark:text-surface-50">{name}</dt>
              <dd className="text-surface-700 dark:text-surface-300">{body}</dd>
            </div>
          ))}
        </dl>
      </Section>

      <Section id="self-help" title="Before you ask">
        <Prose>
          <p>
            The <TextLink href="/docs">documentation</TextLink> covers running PHAEMOS locally and in production. The <TextLink href="/faq">FAQ</TextLink> answers the common questions about machines, alerts and accounts. With the backend running locally, the interactive API reference is at <Code>http://localhost:8000/docs</Code>.
          </p>
        </Prose>
      </Section>

      <Section id="problems" title="Common problems">
        <dl className="max-w-3xl divide-y divide-surface-200 border-y border-surface-200 dark:divide-surface-800 dark:border-surface-800">
          {PROBLEMS.map(({ problem, fix }, i) => (
            <div key={i} className="space-y-2 py-4">
              <dt className="font-medium text-surface-900 dark:text-surface-50">{problem}</dt>
              <dd className="space-y-3 text-surface-700 dark:text-surface-300">{fix}</dd>
            </div>
          ))}
        </dl>
      </Section>
    </PageShell>
  );
}
