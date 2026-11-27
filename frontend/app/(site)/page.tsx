import type { Metadata } from 'next';
import Link from 'next/link';
import AccountDeletedNotice from '@/components/website/AccountDeletedNotice';
import HeroActions from '@/components/website/HeroActions';
import HomePreview from '@/components/website/HomePreview';
import ReadingFlow from '@/components/website/ReadingFlow';
import ReleaseTimeline from '@/components/website/ReleaseTimeline';
import SensorTable from '@/components/website/SensorTable';
import ScoreDiagram from '@/components/website/ScoreDiagram';
import JsonLd from '@/components/content/JsonLd';
import { HOME_FAQ, faqItems, faqJsonLd } from '@/components/content/faq';
import Button from '@/components/ui/Button';
import { loadReleases } from '@/lib/changelogSource';
import { siteAbsolute } from '@/lib/links';
import { REPO_URL } from '@/lib/site';

export const metadata: Metadata = {
  title: { absolute: 'PHAEMOS: open predictive maintenance platform' },
  description:
    'PHAEMOS scores readings from four sensor node types with an Isolation Forest model and shows them on a live dashboard. Open source under AGPL-3.0 with a local quickstart.',
};

const SECTION = 'mx-auto max-w-6xl px-4 py-16 sm:px-6 md:py-20';
const H2 = 'text-3xl font-semibold tracking-[-0.01em] text-surface-900 dark:text-surface-50';
const RULE = 'border-t border-surface-200 dark:border-surface-800';
const BODY = 'text-surface-700 dark:text-surface-300';
const CODE = 'rounded bg-surface-100 px-1 py-0.5 font-mono text-[max(0.8125rem,0.9em)] text-surface-900 dark:bg-surface-800 dark:text-surface-50';

// what it does for the people who run it, one real feature per row. Each line is checked against the FAQ and About pages.
const GAINS: [string, string][] = [
  ['Alerts on drift, not only on limits', 'Each reading is scored against a model of normal behaviour as it arrives, beside the alert rules you set. A slow change can raise an alert before any fixed limit is crossed.'],
  ['The evidence beside the fix', 'A technician turns an alert into a maintenance ticket from the overview, so the readings that raised it stay with the work.'],
  ['One view of the fleet', 'Fleet health, the active alerts grouped by machine and metric and live readings for each machine, on one page.'],
  ['Yours to run and change', 'The software is under AGPL-3.0 and runs on your own server with Docker. The hardware designs are open under CERN-OHL-S.'],
];

// facts the page shows: the name, the address, the repository, the licence and the description above
const STRUCTURED = {
  '@context': 'https://schema.org',
  '@graph': [
    { '@type': 'Organization', name: 'PHAEMOS', url: siteAbsolute('/'), logo: siteAbsolute('/brand/phaemos-emblem-light.png'), sameAs: [REPO_URL] },
    {
      '@type': 'SoftwareSourceCode',
      name: 'PHAEMOS',
      description: 'An open industrial IoT platform for predictive maintenance: sensor nodes, a backend that scores readings against a model of normal behaviour and a live dashboard.',
      codeRepository: REPO_URL,
      license: 'https://www.gnu.org/licenses/agpl-3.0.html',
      programmingLanguage: ['Python', 'TypeScript', 'C++', 'C', 'Rust', 'Go'],
    },
  ],
};

const FOLDERS: [string, string][] = [
  ['backend/', 'FastAPI service: ingest, auth, alerts, tickets and the model'],
  ['frontend/', 'Next.js dashboard, admin panel and these public pages'],
  ['firmware/', 'code for the ESP32, STM32, Arduino Nano and Pico 2W nodes'],
  ['hardware/', 'wiring tables, schematics, PCB layouts and the parts inventory'],
  ['edge/', 'Rust gateway that spools readings through network outages'],
  ['client/', 'Python SDK and simulator, plus a Go CLI'],
  ['infra/', 'Docker Compose stack, Prometheus, Grafana and SQL reports'],
  ['docs/', 'architecture, API, deployment and security'],
];

// static: the three latest releases come from CHANGELOG.md at build time
export default function HomePage() {
  const latest = loadReleases().filter((r) => !r.unreleased).slice(0, 3);
  const faqs = faqItems(HOME_FAQ);

  return (
    <>
      <AccountDeletedNotice />
      <JsonLd data={STRUCTURED} />
      <JsonLd data={faqJsonLd(faqs)} />
      <section aria-labelledby="hero-title" className={RULE.replace('border-t', 'border-b')}>
        <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 py-16 sm:px-6 md:py-24 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
          <div className="min-w-0">
            <h1 id="hero-title" className="max-w-3xl text-4xl font-semibold tracking-[-0.02em] text-surface-900 dark:text-surface-50 md:text-5xl">
              Monitor machines and get an alert when a reading drifts from normal
            </h1>
            <p className={`mt-6 max-w-[64ch] text-base md:text-lg ${BODY}`}>
              Sensor nodes send readings to a backend that scores each one against a model of normal behaviour. The dashboard shows them live and raises an alert when a machine drifts.
            </p>
            <p className={`mt-3 max-w-[64ch] text-base ${BODY}`}>
              The software runs end to end on simulated readings because the sensor nodes are not yet wired to machines.
            </p>
            <div className="mt-8">
              <HeroActions />
            </div>
          </div>
          <ScoreDiagram />
        </div>
      </section>

      <section aria-labelledby="problem-title" className={SECTION}>
        <div className="grid gap-10 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <div className="min-w-0 space-y-4">
            <h2 id="problem-title" className={H2}>Many faults show in the readings before a machine stops</h2>
            <p className={`max-w-[64ch] ${BODY}`}>
              A worn bearing runs warmer and shakes more. A blocked filter changes the current a motor draws. Checked by hand on a round, these changes are easy to miss between visits. A fixed limit only fires once a reading is already far out.
            </p>
            <p className={`max-w-[64ch] ${BODY}`}>
              PHAEMOS is for the maintenance and reliability engineers who look after motors, pumps, fans and compressors. It is also for developers who want an open base for condition monitoring that they can read, change and run themselves.
            </p>
          </div>
          <dl className="min-w-0 divide-y divide-surface-200 border-y border-surface-200 dark:divide-surface-800 dark:border-surface-800">
            {GAINS.map(([title, line]) => (
              <div key={title} className="grid gap-1 py-5 md:grid-cols-[14rem_1fr] md:gap-6">
                <dt className="text-base font-semibold text-surface-900 dark:text-surface-50">{title}</dt>
                <dd className={`max-w-[60ch] text-base ${BODY}`}>{line}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <section aria-labelledby="preview-title" className={RULE}>
        <div className={SECTION}>
        <h2 id="preview-title" className={`${H2} mb-8`}>The dashboard itself</h2>
        <HomePreview />
        </div>
      </section>

      <section aria-labelledby="sensors-title" className={`${RULE}`}>
        <div className={SECTION}>
          <h2 id="sensors-title" className={H2}>What it measures</h2>
          <p className={`mt-3 mb-8 max-w-[64ch] ${BODY}`}>
            Four node types carry these sensors. Together they cover temperature, vibration, current, gas, sound, distance and shaft speed.
          </p>
          <SensorTable />
          <p className="mt-4 max-w-[72ch] text-base text-surface-600 dark:text-surface-400">
            The Nano and the Pico 2W also accept a BMP280, which has no humidity element. The nodes are designed and not yet built. The carrier board for each node is fully designed and checked and waits to be manufactured.
          </p>
        </div>
      </section>

      <section aria-labelledby="flow-title" className={RULE}>
        <div className={SECTION}>
          <h2 id="flow-title" className={H2}>How a reading travels</h2>
          <p className={`mt-3 mb-8 max-w-[64ch] ${BODY}`}>One reading from a sensor node to the dashboard, with the link and the format at each step.</p>
          <ReadingFlow />
        </div>
      </section>

      <section aria-labelledby="run-title" className={RULE}>
        <div className={SECTION}>
          <h2 id="run-title" className={H2}>Run it yourself</h2>
          <div className="mt-6 grid gap-10 lg:grid-cols-2">
            <div className="space-y-4">
              <p className={`max-w-[64ch] ${BODY}`}>
                The software is licensed under the GNU Affero General Public License v3 or later. The hardware designs are under the CERN Open Hardware Licence v2, Strongly Reciprocal.
              </p>
              <p className={`max-w-[64ch] ${BODY}`}>
                With Docker and Node.js installed, two commands start the database, Redis, the API and this dashboard. The dashboard is then on <code className={CODE}>localhost:3000</code> and the API on <code className={CODE}>localhost:8000</code>.
              </p>
              <pre className="overflow-x-auto rounded-lg border border-surface-200 bg-surface-100 p-4 font-mono text-base text-surface-900 dark:border-surface-800 dark:bg-surface-900 dark:text-surface-50" tabIndex={0}>
                <code>{'cp .env.example .env\nmake dev'}</code>
              </pre>
              <p className={`max-w-[64ch] ${BODY}`}>
                With no hardware, the simulator in <code className={CODE}>client/python</code> produces readings for any of the four node types.
              </p>
              <div className="pt-2">
                <Button href={REPO_URL} external variant="secondary">
                  View the repository on GitHub
                </Button>
              </div>
            </div>
            <div>
              <h3 className="mb-3 text-base font-semibold text-surface-900 dark:text-surface-50">What the monorepo holds</h3>
              <dl className="divide-y divide-surface-200 border-y border-surface-200 dark:divide-surface-800 dark:border-surface-800">
                {FOLDERS.map(([name, what]) => (
                  <div key={name} className="grid gap-1 py-2.5 sm:grid-cols-[6.5rem_1fr] sm:gap-4">
                    <dt className="text-base text-surface-900 dark:text-surface-50"><code>{name}</code></dt>
                    <dd className="text-base text-surface-700 dark:text-surface-300">{what}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </div>
        </div>
      </section>

      <section aria-labelledby="faq-title" className={RULE}>
        <div className={SECTION}>
          <h2 id="faq-title" className={`${H2} mb-8`}>Five questions people ask first</h2>
          <div className="grid gap-x-12 gap-y-8 lg:grid-cols-2">
            {faqs.map(({ q, a }) => (
              <div key={q} className="min-w-0 max-w-[64ch]">
                <h3 className="text-lg font-semibold text-surface-900 dark:text-surface-50">{q}</h3>
                <div className={`mt-2 space-y-3 ${BODY}`}>{a}</div>
              </div>
            ))}
          </div>
          <Link href="/faq" className="mt-8 inline-flex min-h-[44px] items-center text-brand-800 underline underline-offset-2 hover:no-underline dark:text-brand-400">
            Read all the answers
          </Link>
        </div>
      </section>

      {latest.length > 0 && (
        <section aria-labelledby="releases-title" className={RULE}>
          <div className={SECTION}>
            <h2 id="releases-title" className={`${H2} mb-10`}>Latest releases</h2>
            <ReleaseTimeline releases={latest} headingLevel={3} yearMarkers={false} />
            <Link href="/changelog" className="inline-flex min-h-[44px] items-center text-brand-800 underline underline-offset-2 hover:no-underline dark:text-brand-400">
              See every release
            </Link>
          </div>
        </section>
      )}
    </>
  );
}
