import type { ReactNode } from 'react';
import { isValidElement } from 'react';
import { BulletList, Code } from '@/components/content/Prose';
import TextLink from '@/components/content/TextLink';
import { appHref } from '@/lib/links';

// the questions and answers of the FAQ page, kept here so the home page can show a few of them word for word and both
// pages can describe them as structured data without a second copy that could drift.
const GH = 'https://github.com/phaemos/phaemos/blob/main';

export interface FaqItem {
  q: string;
  a: ReactNode;
}

// every answer describes behaviour read from the code (backend/app and frontend/) or the repository documents. It
// says where a thing can be done and what it does and never quotes a button label, so a rename cannot make it false.
export const FAQ_SECTIONS: { id: string; title: string; items: FaqItem[] }[] = [
  {
    id: 'start',
    title: 'Getting started',
    items: [
      {
        q: 'What is PHAEMOS?',
        a: (
          <>
            <p>
              Sensor nodes send readings to a backend. The backend scores each reading with an Isolation Forest model and checks it against alert rules. A live dashboard shows the readings and raises alerts and tickets when a machine drifts from normal.
            </p>
            <p>
              The software runs end to end today on simulated readings. The sensor nodes are not yet wired to machines. <TextLink href="/about">About</TextLink> says what is built and what is not.
            </p>
          </>
        ),
      },
      {
        q: 'How do I run it on my own computer?',
        a: (
          <>
            <p>
              Clone the repository, copy <Code>.env.example</Code> to <Code>.env</Code> and run <Code>make dev</Code> from the repository root. The dashboard is then on <Code>http://localhost:3000</Code> and the API on <Code>http://localhost:8000</Code>.
            </p>
            <p>
              With no hardware, install the simulator with <Code>pip install -e client/python</Code> and run <Code>phaemos-sim --node esp32 --count 5 --dry-run</Code>. The <TextLink href={`${GH}/docs/development.md`}>development guide</TextLink> covers running without Docker and the tests.
            </p>
          </>
        ),
      },
      {
        q: 'How do I add a machine?',
        a: (
          <>
            <p>
              An admin adds machines on the <TextLink href={appHref('/devices')}>Machines</TextLink> page. The API creates the machine and returns its API key. A key is stored only as a keyed hash, so it is shown only when a machine is created or its key is replaced. Copy it then and put it in the node&apos;s firmware configuration.
            </p>
            <p>
              The node posts each reading to <Code>POST /api/v1/telemetry</Code> with the key in the <Code>X-API-Key</Code> header. The machine shows as online once the first reading arrives.
            </p>
          </>
        ),
      },
      {
        q: 'Why does a machine not show as online?',
        a: (
          <>
            <p>The usual causes are:</p>
            <BulletList>
              <li>The key in the firmware does not match the machine&apos;s key. The API answers 401 with &quot;Invalid API key&quot;.</li>
              <li>The node posts to the wrong address. The path is <Code>/api/v1/telemetry</Code> with no machine id in it.</li>
              <li>The node cannot reach the API from its network.</li>
            </BulletList>
          </>
        ),
      },
      {
        q: 'Does a machine go offline when its readings stop?',
        a: (
          <p>
            Yes. Every post from a node counts as a sign of life. The Machines page shows a machine as late once its node has missed about 4 of its expected posts and as offline after about 12 and it shows when the machine last reported. When a node has been silent for 2 minutes PHAEMOS raises a warning alert for it and the alert resolves itself when the node posts again. After the service itself restarts, nodes get a short grace before they count as late, so a restart does not make every machine look silent.
          </p>
        ),
      },
    ],
  },
  {
    id: 'machines',
    title: 'Machines and sensors',
    items: [
      {
        q: 'Which sensors and nodes does it support?',
        a: (
          <p>
            Four node types: an ESP32 hub, an STM32 Black Pill for vibration, an Arduino Nano and a Raspberry Pi Pico 2W. The <TextLink href={`${GH}/docs/sensor_reference.md`}>sensor reference</TextLink> lists every sensor with its interface and range.
          </p>
        ),
      },
      {
        q: 'How does the STM32 reach the ESP32?',
        a: (
          <p>
            Over a serial line at 115200 baud. The STM32 sends one line of the form <Code>VIB:x,y,z,MAG:m,FFT_PEAK:nHz</Code> and the ESP32 adds those values to the reading it posts. The pin table is in the <TextLink href={`${GH}/firmware/stm32_blackpill/README.md`}>STM32 firmware guide</TextLink>.
          </p>
        ),
      },
      {
        q: 'How do I replace a machine’s API key?',
        a: (
          <p>
            An admin or the person who owns the machine, can replace it with <Code>POST /api/v1/devices/{'{id}'}/rotate-key</Code>. It asks for their password (or a current two-step code) first and only a signed-in session can do it, not an API token. A technician who only shares a machine nobody owns cannot. The response carries the new key, which is shown once and the old key stops working at once. Update the firmware afterwards.
          </p>
        ),
      },
      {
        q: 'What are tags?',
        a: (
          <p>
            Short labels such as <Code>production</Code> or <Code>conveyor-3</Code>. An admin adds and removes them. They show with the machine. The API can list only the machines with a given tag.
          </p>
        ),
      },
    ],
  },
  {
    id: 'alerts',
    title: 'Alerts and maintenance',
    items: [
      {
        q: 'How do alert rules work?',
        a: (
          <>
            <p>
              A rule names a machine, a reading, a comparison (above, below or equal to), a threshold and a severity of info, warning or critical. Every reading a machine sends is checked against that machine&apos;s rules. A match creates an alert on the <TextLink href={appHref('/alerts')}>Alerts</TextLink> page. Admins create and change rules.
            </p>
            <p>
              Warning and critical alerts can also send an email to the alert addresses the installation is set up with. Critical alerts send a text message to the machine&apos;s owner when email and text messages are configured and the owner has added a phone number. An email or text for the same machine, reading and severity repeats at most once an hour.
            </p>
            <p>An alert stays open until someone resolves it.</p>
          </>
        ),
      },
      {
        q: 'How does an alert become a ticket?',
        a: (
          <p>
            An anomaly alert opens its own ticket, named after the machine. If that machine already has an open ticket from an earlier anomaly the alert is added to it. For an alert from a rule, create the ticket from the <TextLink href={appHref('/dashboard')}>overview</TextLink>. Tickets are listed on the <TextLink href={appHref('/tickets')}>Tickets</TextLink> page.
          </p>
        ),
      },
      {
        q: 'What is a maintenance window?',
        a: (
          <p>
            A set period in which alerts are silenced so planned work does not raise them. An admin creates one under <TextLink href={appHref('/admin')}>Admin</TextLink>. While it runs the overview shows a notice with the end time. Readings are still stored.
          </p>
        ),
      },
      {
        q: 'How do webhooks work?',
        a: (
          <>
            <p>
              An admin adds a webhook address under <TextLink href={appHref('/admin')}>Admin</TextLink> and proves it is them again with their password first (a webhook sends every alert to an address they choose). The address must start with https:// and point at a public server. An address on a private network is refused. When an alert rule fires, PHAEMOS sends a message with the machine, the reading and its threshold and the severity to every enabled webhook.
            </p>
            <p>
              There are two formats. A chat webhook sends a short message for Slack, Discord or Microsoft Teams in that service&apos;s own format, with wording you can change. A signed JSON webhook sends the whole alert as JSON for a program to read. Every delivery is signed with a secret that is shown once when you add it. A test message can be sent to check a webhook before you rely on it. The list says in words what happened to the last delivery and how many have failed in a row.
            </p>
          </>
        ),
      },
      {
        q: 'How do I check that a webhook came from PHAEMOS?',
        a: (
          <>
            <p>
              Every signed JSON delivery has an <Code>X-Phaemos-Signature</Code> header that looks like <Code>t=1790000000,v1=9f2c…</Code>. The <Code>v1</Code> part is the HMAC-SHA256, using your webhook&apos;s secret, of the timestamp, a full stop and the exact bytes of the body. Work it out over the raw body you received and not over JSON you have read and written out again. Compare the two in constant time and refuse a timestamp more than five minutes from your own clock, which stops a replay.
            </p>
            <p>
              Delivery is at least once, so a later reminder for the same alert has a new delivery id and the same <Code>data.alert.id</Code>. Use that to avoid acting twice. If the secret is lost, an admin can make a new one, which stops the old one signing at once. The <TextLink href={`${GH}/docs/api-reference.md#verifying-the-signature`}>API reference</TextLink> has the code for checking a signature.
            </p>
          </>
        ),
      },
      {
        q: 'What should I quote in a bug report?',
        a: (
          <p>
            When something fails the dashboard shows a short reference in small text beside the message. Quote it. Every error from the API carries the same reference in its <Code>request_id</Code> field and in an <Code>X-Request-ID</Code> header and it is in the server log, so we can find the exact request. Add what you did and what you expected. Never paste a password, an API token, a signing secret or a reset link: the reference is enough and we never need those.
          </p>
        ),
      },
    ],
  },
  {
    id: 'model',
    title: 'The anomaly model',
    items: [
      {
        q: 'What is the anomaly score?',
        a: (
          <>
            <p>
              Every reading gets a score from 0 to 1 when it arrives. A score of 0.7 or more counts as an anomaly. Each machine&apos;s chart draws the score against the 0.7 line.
            </p>
            <p>
              The general model reads six values: temperature, humidity, vibration on three axes and light level. A node type with at least 50 readings also gets its own model on its own sensors. A reading is scored by the node&apos;s own model when it has every input that model needs and by the general model when it does not. It is left unscored only when neither can and a missing value is never counted as zero. A sensor that has failed raises its own monitoring alert. The model learns from normal readings only, so it needs no labelled faults.
            </p>
          </>
        ),
      },
      {
        q: 'When does an anomaly raise an alert?',
        a: (
          <p>
            When at least four in every five scored readings in a window score 0.7 or more. The window is the longer of two minutes and 24 posting intervals and it shrinks to a minute when the scores are clearly high. The alert is critical when the median score of the window is 0.85 or more and a warning below that. It clears by itself after a calm spell of at least half an hour whose median score is under 0.5.
          </p>
        ),
      },
      {
        q: 'Does the model retrain itself?',
        a: (
          <p>
            Yes. A retrain runs every night at 03:30 UTC and an admin can also start one with <Code>POST /api/v1/ml/retrain</Code>. Each reads the last 14 days of every machine. A new model replaces the one in service only if it passes the checks on false alerts and on the newest readings. Otherwise the old model stays and the reason is recorded. A new model loads without a restart and a manual retrain has to wait an hour after the last one.
          </p>
        ),
      },
    ],
  },
  {
    id: 'accounts',
    title: 'Accounts',
    items: [
      {
        q: 'How do I get an account?',
        a: (
          <p>
            An admin invites you by email. The link in the email works for 48 hours. Open it and choose your name and a password. You can also sign in with Google, GitHub or Microsoft when the installation has that provider set up.
          </p>
        ),
      },
      {
        q: 'How do I turn on two-step sign-in?',
        a: (
          <p>
            On your <TextLink href={appHref('/profile')}>profile</TextLink> page. Scan the QR code with an authenticator app and enter the 6-digit code to confirm. After that every sign-in asks for a code. There are no backup codes yet. If you lose your authenticator, an administrator can clear two-step for you under People in the Admin area. That ends every session you have and you then sign in with your password and can turn it on again.
          </p>
        ),
      },
      {
        q: 'I forgot my password. What now?',
        a: (
          <p>
            There is no &ldquo;forgot password&rdquo; request yet. Ask an administrator to send you a reset link: it goes to your own address, works once and lasts 2 hours. You can change a password you know on your <TextLink href={appHref('/profile')}>profile</TextLink> page. Wrong passwords never lock an account for good: after a few the place they came from has to wait, a little longer each time and the page says how long.
          </p>
        ),
      },
      {
        q: 'What can an administrator do about a person who has left or lost access?',
        a: (
          <>
            <p>
              An administrator can invite and cancel invitations, change a person&apos;s role, deactivate and reactivate an account, clear a person&apos;s two-step sign-in, send a reset link to the person&apos;s own address and remove an account. Each of those asks the administrator to prove it is them again. An administrator cannot do these to their own account and the product always keeps at least one active admin.
            </p>
            <p>
              A person leaving is deactivated, which ends every session they have at once or removed once they no longer own machines. A person can also end their own sessions or all but the current one, under Where you are signed in on their profile page.</p>
          </>
        ),
      },
      {
        q: 'How do I download or delete my data?',
        a: (
          <p>
            Both are on your <TextLink href={appHref('/profile')}>profile</TextLink> page. The download is a JSON file with your profile, the machines you own, the tickets you raised or were assigned, the maintenance windows you created and your own entries in the log of changes. Deleting asks you to prove it is you first, with your password and, if two-step sign-in is on, a current code (an account that signs in through a provider uses a code or a recent sign-in with the provider). It is refused while you own machines or are the last admin. Deleting takes your name off the tickets you raised and cannot be undone.
          </p>
        ),
      },
    ],
  },
  {
    id: 'hosting',
    title: 'Hosting and licence',
    items: [
      {
        q: 'Can I host it myself?',
        a: (
          <p>
            Yes. The stack runs with Docker Compose. The <TextLink href={`${GH}/docs/deployment.md`}>deployment guide</TextLink> sets up the API, the database and Redis on one server and the dashboard on Vercel. The other documents are on the <TextLink href="/docs">documentation</TextLink> page.
          </p>
        ),
      },
      {
        q: 'What does the licence mean for me?',
        a: (
          <>
            <p>
              The software is under the GNU Affero General Public License v3.0 or later. You can use, study, modify and self-host it. If you run a modified version as a network service you must make your modified source available to that service&apos;s users.
            </p>
            <p>
              The hardware designs are under the CERN Open Hardware Licence v2, Strongly Reciprocal. The <TextLink href={`${GH}/NOTICE.md`}>licensing notice</TextLink> says which licence covers which part and the licence files hold the exact terms.
            </p>
          </>
        ),
      },
    ],
  },
];

// the five questions the home page answers, by their exact wording here
export const HOME_FAQ = [
  'What is PHAEMOS?',
  'How do I run it on my own computer?',
  'When does an anomaly raise an alert?',
  'How do I get an account?',
  'Can I host it myself?',
];

export function faqItems(questions: string[]): FaqItem[] {
  const all = FAQ_SECTIONS.flatMap((s) => s.items);
  return questions.map((q) => {
    const item = all.find((i) => i.q === q);
    if (!item) throw new Error(`no FAQ answer for "${q}"`);
    return item;
  });
}

// the plain text of an answer, for structured data. It walks the elements rather than rendering them, so it works in a
// server component and the text is the same words a reader sees.
export function textOf(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(textOf).join('');
  if (isValidElement<{ children?: ReactNode }>(node)) {
    const inner = textOf(node.props.children);
    // a paragraph or list item ends with a space so two blocks never run together
    return typeof node.type === 'string' && ['p', 'li'].includes(node.type) ? `${inner} ` : inner;
  }
  return '';
}

// FAQPage structured data for a list of answers that are visible on the page
export function faqJsonLd(items: FaqItem[]) {
  return {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: items.map((i) => ({
      '@type': 'Question',
      name: i.q,
      acceptedAnswer: { '@type': 'Answer', text: textOf(i.a).replace(/\s+/g, ' ').trim() },
    })),
  };
}
