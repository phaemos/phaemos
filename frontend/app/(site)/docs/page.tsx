import type { Metadata } from 'next';
import PageShell from '@/components/content/PageShell';
import Section from '@/components/content/Section';
import Prose, { Code } from '@/components/content/Prose';
import TextLink from '@/components/content/TextLink';
import { DOCS_ON_GITHUB } from '@/components/content/legal';

export const metadata: Metadata = {
  title: 'Documentation',
  description: 'The PHAEMOS documents: setup, architecture, the API and sensor reference and security.',
};

interface Doc {
  name: string;
  // the page on the docs site, from the file name in docs/ and the nav in mkdocs.yml
  path: string;
  line: string;
}

// the groups follow mkdocs.yml. Each line is checked against the opening of the document it describes.
const GROUPS: { id: string; title: string; docs: Doc[] }[] = [
  {
    id: 'run',
    title: 'Run it',
    docs: [
      { name: 'Development', path: 'development', line: 'Running locally with or without Docker, the smoke test, the simulator and the tests.' },
      { name: 'Deployment', path: 'deployment', line: 'The server, Vercel and DNS setup for production.' },
      { name: 'Scalability', path: 'scalability', line: 'When and how to scale each layer beyond one server.' },
    ],
  },
  {
    id: 'understand',
    title: 'Understand it',
    docs: [
      { name: 'Architecture', path: 'architecture', line: 'The layers, how a reading travels, authentication, background tasks and webhooks.' },
      { name: 'Tech stack', path: 'tech-stack', line: 'Every language and tool by layer, plus the four boards.' },
      { name: 'Repositories', path: 'repositories', line: 'The monorepo and the component repositories it is published to.' },
    ],
  },
  {
    id: 'reference',
    title: 'Reference',
    docs: [
      { name: 'API reference', path: 'api-reference', line: 'Every REST endpoint with its authentication and its request and response shapes.' },
      { name: 'Sensor reference', path: 'sensor_reference', line: 'Every sensor with its interface, range and wiring.' },
      { name: 'Database schema', path: 'schema', line: 'The PostgreSQL tables and how they relate.' },
      { name: 'Security', path: 'security', line: 'The security controls and where each one is implemented.' },
    ],
  },
  {
    id: 'project',
    title: 'The project',
    docs: [
      { name: 'Releases', path: 'releases', line: 'How a release is tagged and how the changelog is checked.' },
    ],
  },
];

export default function DocsPage() {
  return (
    <PageShell
      title="Documentation"
      lead="The documents live in the docs folder of the repository and build into a documentation site."
    >
      <Prose className="mb-10">
        <p>
          The documentation site, docs.phaemos.com, goes live with the launch milestone and is not linked here until then. Until then the same files are in the <TextLink href={DOCS_ON_GITHUB}>docs folder on GitHub</TextLink>. Running <Code>make docs</Code> serves the site on your own machine.
        </p>
      </Prose>

      {GROUPS.map(({ id, title, docs }) => (
        <Section key={id} id={id} title={title}>
          <dl className="max-w-3xl divide-y divide-surface-200 border-y border-surface-200 dark:divide-surface-800 dark:border-surface-800">
            {docs.map((doc) => (
              <div key={doc.path} className="grid gap-x-6 sm:grid-cols-[12rem_1fr]">
                <dt className="font-medium">
                  <TextLink href={`${DOCS_ON_GITHUB}/${doc.path}.md`} className="inline-flex min-h-[44px] items-center">{doc.name}</TextLink>
                </dt>
                <dd className="pb-3 text-surface-700 dark:text-surface-300 sm:py-3">{doc.line}</dd>
              </div>
            ))}
          </dl>
        </Section>
      ))}

      <Prose className="mt-10">
        <p>
          Can&apos;t find an answer? Read the <TextLink href="/faq">FAQ</TextLink> or see <TextLink href="/support">support</TextLink>.
        </p>
      </Prose>
    </PageShell>
  );
}
