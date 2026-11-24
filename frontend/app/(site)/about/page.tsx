import type { Metadata } from 'next';
import PageShell from '@/components/content/PageShell';
import Section from '@/components/content/Section';
import Prose, { BulletList, Code } from '@/components/content/Prose';
import TextLink from '@/components/content/TextLink';
import DataTable from '@/components/ui/DataTable';
import { REPO_URL } from '@/lib/site';

export const metadata: Metadata = {
  title: 'About',
  description: 'What PHAEMOS is, how a reading travels through it and what works today.',
};

// each row is checked against package.json, backend/requirements.txt and backend/app
const STACK: { layer: string; items: string }[] = [
  { layer: 'Dashboard', items: 'Next.js 16, React 19, Tailwind CSS 4, Recharts' },
  { layer: 'Backend', items: 'FastAPI, SQLAlchemy, PostgreSQL' },
  { layer: 'Redis', items: 'Notification cooldowns and the status check' },
  { layer: 'Model', items: 'scikit-learn Isolation Forest' },
  { layer: 'Sign-in', items: 'Email and password with an optional authenticator code, Google, GitHub and Microsoft' },
  { layer: 'Nodes', items: 'ESP32, STM32 Black Pill, Arduino Nano and Raspberry Pi Pico 2W' },
  { layer: 'Operations', items: 'Docker Compose, GitHub Actions, Prometheus and Grafana' },
];

export default function AboutPage() {
  return (
    <PageShell
      title="One repository from the sensor to the ticket"
      lead="Sensor nodes send readings to a backend that scores each one against a model of normal behaviour. A reading that drifts raises an alert and a ticket."
    >
      <Section id="status" title="Where it stands">
        <Prose>
          <p>
            The software runs end to end today: ingest, storage, scoring, alerts, tickets and the dashboard. It runs on simulated readings, because the sensor nodes are not yet wired to machines.
          </p>
          <p>
            The firmware for all four node types is in the repository. The nodes are designed and not yet built. The plan is to prototype on development boards and breakouts. The boards that would carry them are still being designed. The model has not yet been trained on readings from a real machine.
          </p>
        </Prose>
      </Section>

      <Section id="why" title="Why we built it">
        <Prose>
          <p>
            Most maintenance starts after the failure: a machine stops, someone notices and a ticket gets filed. We measure continuously, score each reading against what normal looks like and raise the alert while the machine is still running.
          </p>
        </Prose>
      </Section>

      <Section id="how" title="How a reading travels">
        <Prose>
          <ol className="list-decimal space-y-3 pl-5 marker:text-surface-500">
            <li>
              A node reads its sensors. The STM32 samples an accelerometer at 100 Hz and runs a 128-point FFT to find the dominant vibration frequency. The STM32 and the Arduino Nano send their readings to the ESP32 over serial lines. The Pico 2W posts over Wi-Fi by itself.
            </li>
            <li>
              The ESP32 posts a reading every 5 seconds to the API at <Code>POST /api/v1/telemetry</Code>. The machine&apos;s API key goes in the <Code>X-API-Key</Code> header.
            </li>
            <li>
              The backend scores the reading from 0 to 1 with an Isolation Forest and stores it in PostgreSQL. A score of 0.7 or more counts as an anomaly. The model learns from normal readings only, so it needs no labelled faults.
            </li>
            <li>
              The backend checks the reading against the alert rules. An anomaly alert is raised when at least four in five scored readings in a window score 0.7 or more. It opens a ticket for the machine.
            </li>
            <li>The backend pushes the reading to the dashboard over a WebSocket.</li>
          </ol>
          <p>
            A general model scores every reading. A node type with enough history also gets its own model. Redis holds notification cooldowns, so one fault does not send the same email or text every few seconds.
          </p>
        </Prose>
      </Section>

      <Section id="roles" title="Roles">
        <Prose>
          <p>There are three roles.</p>
          <BulletList>
            <li>Viewers see every machine and its readings. A new account starts as a viewer.</li>
            <li>Technicians see the machines assigned to them and any machine nobody owns yet.</li>
            <li>Admins manage machines, accounts and the rules that raise alerts.</li>
          </BulletList>
        </Prose>
      </Section>

      <Section id="stack" title="What it is built with">
        <DataTable caption="The layers of PHAEMOS and what each is built with" maxHeightClass="max-h-none" framed className="max-w-[72ch]">
          <thead>
            <tr>
              <th scope="col">Layer</th>
              <th scope="col">Built with</th>
            </tr>
          </thead>
          <tbody>
            {STACK.map(({ layer, items }) => (
              <tr key={layer}>
                <th scope="row">{layer}</th>
                <td>{items}</td>
              </tr>
            ))}
          </tbody>
        </DataTable>
        <Prose className="mt-4">
          <p>
            Every sensor, with its range and wiring, is in the{' '}
            <TextLink href="https://github.com/phaemos/phaemos/blob/main/docs/sensor_reference.md">sensor reference</TextLink>. The other documents are listed on the <TextLink href="/docs">documentation page</TextLink>.
          </p>
        </Prose>
      </Section>

      <Section id="licence" title="Licence">
        <Prose>
          <p>
            The software is licensed under the GNU Affero General Public License v3.0 or later. The hardware designs are licensed under the CERN Open Hardware Licence v2, Strongly Reciprocal. The source is on <TextLink href={REPO_URL}>GitHub</TextLink>.
          </p>
        </Prose>
      </Section>

      <Section id="contact" title="Contact">
        <Prose>
          <p>
            Email <TextLink href="mailto:contact@phaemos.com">contact@phaemos.com</TextLink> or use the <TextLink href="/contact">contact form</TextLink>. Questions about setup are better asked in <TextLink href="https://github.com/phaemos/phaemos/discussions">GitHub Discussions</TextLink>, where the answers stay searchable.
          </p>
        </Prose>
      </Section>
    </PageShell>
  );
}
