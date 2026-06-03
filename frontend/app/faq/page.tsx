import type { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'FAQ - PHAEMOS',
  description: 'Frequently asked questions about PHAEMOS - setup, devices, sensors, alerts, anomaly detection, maintenance windows, webhooks, account management, deployment and licensing.',
};

const code = (s: string) => (
  <code className="text-xs bg-surface-100 dark:bg-surface-800 px-1 py-0.5 rounded font-mono">{s}</code>
);

const FAQ_SECTIONS = [
  {
    title: 'Getting started',
    items: [
      {
        q: 'What is PHAEMOS?',
        a: (
          <>
            PHAEMOS is an open-source industrial IoT predictive maintenance platform. It collects
            real-time sensor data from ESP32, STM32, Arduino Nano and Raspberry Pi Pico 2W hardware
            nodes, stores it in PostgreSQL, and displays it on a live Next.js dashboard. When sensor
            readings cross a threshold the platform fires an alert, dispatches a webhook notification
            and can send an SMS. An Isolation Forest machine learning model scores every telemetry
            reading for anomalies - flagging unusual behaviour before a visible fault occurs.
          </>
        ),
      },
      {
        q: 'How do I run PHAEMOS locally?',
        a: (
          <>
            Clone the repo, copy {code('backend/.env.example')} to {code('backend/.env')}, then run{' '}
            {code('make dev')} from the repo root. This starts the FastAPI backend, PostgreSQL,
            Redis and the Next.js frontend via Docker Compose. The dashboard is at{' '}
            {code('http://localhost:3000')} and the API at {code('http://localhost:8000')}.
            See the{' '}
            <a
              href="https://docs.phaemos.com/deployment"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary-400 hover:underline"
            >
              deployment guide
            </a>{' '}
            for full production setup on a DigitalOcean VPS.
          </>
        ),
      },
      {
        q: 'How do I add a device?',
        a: (
          <>
            Go to the <Link href="/devices" className="text-primary-400 hover:underline">Devices</Link> page
            and click <strong>Add device</strong>. Give it a name and an optional description, then
            copy the generated API key. Set that key as the {code('PHAEMOS_API_KEY')} environment
            variable in your firmware. The device appears as online within seconds of the first
            successful telemetry POST to {code('POST /api/v1/telemetry/{device_id}')}.
          </>
        ),
      },
      {
        q: 'Why is my device showing as offline?',
        a: (
          <>
            A device is marked offline if no telemetry POST has been received in the last 30 seconds.
            Common causes: the firmware API key does not match the one on the device detail page
            (rotate it if lost), the {code('NEXT_PUBLIC_API_URL')} environment variable points to
            the wrong host, or the firmware is sending to the wrong device ID in the URL path.
            Check the browser network tab on the device detail page - a healthy device shows the
            last-seen timestamp updating every 5 seconds.
          </>
        ),
      },
    ],
  },
  {
    title: 'Devices and sensors',
    items: [
      {
        q: 'What sensors and firmware nodes are supported?',
        a: (
          <>
            PHAEMOS reads 11 sensor channels across four firmware nodes:
            <ul className="mt-2 space-y-1 list-disc list-inside">
              <li><strong>ESP32 primary node</strong> - DHT22 (temperature/humidity), MQ-135 (air quality), INA219 (current/voltage), ACS712 (current), HC-SR04 (distance), IR sensor, buzzer, RGB LED, relay, OLED</li>
              <li><strong>STM32 Black Pill F411</strong> - MPU-6050 at 100 Hz with 128-point CMSIS-DSP FFT for vibration X/Y/Z and peak frequency; UART output forwarded by the ESP32</li>
              <li><strong>Arduino Nano</strong> - BME280 (pressure/temperature/humidity), LDR (light), FC-28 (soil moisture); serial output parsed by the ESP32</li>
              <li><strong>Raspberry Pi Pico 2W</strong> - BME280, LDR, OLED; posts directly to the API over Wi-Fi</li>
            </ul>
            <span className="mt-2 block">
              See the{' '}
              <a
                href="https://github.com/zaccesss/phaemos/blob/main/docs/sensor_reference.md"
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary-400 hover:underline"
              >
                sensor reference
              </a>{' '}
              for wiring diagrams, calibration notes and the full data dictionary.
            </span>
          </>
        ),
      },
      {
        q: 'How does the STM32 connect to the ESP32?',
        a: (
          <>
            The STM32 Black Pill sends its vibration telemetry over UART at 115200 baud using the
            format {code('VIB:x,y,z,MAG:m,FFT_PEAK:nHz')}. The ESP32 reads this on its hardware
            serial RX pin, parses the line, and merges the values into the main telemetry payload
            before posting to the API. No additional library is needed on the ESP32 side - plain{' '}
            {code('Serial2.readStringUntil(\'\\n\')')} is sufficient. See{' '}
            <a
              href="https://github.com/zaccesss/phaemos/blob/main/firmware/stm32_blackpill/README.md"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary-400 hover:underline"
            >
              firmware/stm32_blackpill/README.md
            </a>{' '}
            for the pin wiring table.
          </>
        ),
      },
      {
        q: 'What is the API key and how do I rotate it?',
        a: (
          <>
            Each device has a unique API key used by the firmware to authenticate telemetry POSTs.
            The key is sent in the {code('X-API-Key')} request header. It is stored as a SHA-256
            hash on the server - the plaintext is shown only once at creation. If you lose it, open
            the device detail page and click <strong>Rotate API key</strong>. A new key is generated
            immediately; the old one is invalidated. Update your firmware environment variable
            ({code('PHAEMOS_API_KEY')}) after rotating. The device key only grants access to the
            telemetry ingest endpoint - it cannot be used to log in or call any other API route.
          </>
        ),
      },
      {
        q: 'How do device tags work?',
        a: (
          <>
            Tags are freeform labels you attach to devices (e.g. {code('production')},{' '}
            {code('building-a')}, {code('conveyor-3')}). Add or remove them from the device detail
            page. On the <Link href="/devices" className="text-primary-400 hover:underline">Devices</Link> page
            you can filter by tag to see only a subset of your fleet. Tags are stored as a
            PostgreSQL array column and are indexed for fast filtering. There is no limit on the
            number of tags per device.
          </>
        ),
      },
    ],
  },
  {
    title: 'Alerts and maintenance',
    items: [
      {
        q: 'How do alert rules work?',
        a: (
          <>
            Alert rules define a sensor channel, a comparison operator (above/below/equals) and a
            numeric threshold. Every telemetry reading that is stored triggers evaluation of all
            active rules for that device. When a rule fires, the platform creates an alert, dispatches
            any configured webhook (Slack, Discord or Teams), and sends an SMS if the severity is
            set to critical. Alerts stay open until you mark them resolved manually. You can escalate
            any alert to a maintenance ticket in one click from the{' '}
            <Link href="/alerts" className="text-primary-400 hover:underline">Alerts</Link> page.
          </>
        ),
      },
      {
        q: 'What are maintenance windows?',
        a: (
          <>
            A maintenance window is a scheduled time range during which alert rules are suppressed
            for one or all devices. Use them when you are doing planned work and do not want false
            alerts flooding your notifications. While a window is active an amber banner appears on
            the dashboard. Create a window from the{' '}
            <Link href="/admin/maintenance" className="text-primary-400 hover:underline">Maintenance</Link> page
            (admin only). Windows have a start time, end time, and an optional note. They are stored
            in UTC; the dashboard converts to your browser timezone.
          </>
        ),
      },
      {
        q: 'How do webhooks work?',
        a: (
          <>
            Webhooks dispatch an HTTP POST to a URL of your choice when an alert fires. PHAEMOS
            supports Slack, Discord and Microsoft Teams out of the box - each has a pre-formatted
            payload that renders as a notification in your channel. You can also use a generic
            webhook for custom integrations. Configure webhooks from the{' '}
            <Link href="/admin/webhooks" className="text-primary-400 hover:underline">Webhooks</Link> page
            (admin only). Each webhook can be enabled or disabled independently, and you can send a
            test payload to verify delivery before going live.
          </>
        ),
      },
    ],
  },
  {
    title: 'Machine learning',
    items: [
      {
        q: 'What is the ML anomaly score?',
        a: (
          <>
            The anomaly score is produced by an Isolation Forest model trained on the last 30 days
            of normal telemetry for each device. Scores range from roughly -0.5 (highly anomalous)
            to +0.5 (typical behaviour). A score below -0.1 triggers an ML alert. The model uses 7
            feature columns: temperature, vibration X/Y/Z, FFT peak frequency, current and voltage.
            It learns what is normal for each individual device - an idle motor and a running motor
            each have their own model. See the{' '}
            <Link href="/blog/isolation-forest-anomaly-detection" className="text-primary-400 hover:underline">
              anomaly detection blog post
            </Link>{' '}
            for a full explanation of how Isolation Forest works.
          </>
        ),
      },
      {
        q: 'When does the model retrain and can I trigger it manually?',
        a: (
          <>
            The model retrains automatically via a daily scheduled job at 02:00 UTC. You can also
            trigger a manual retrain by calling{' '}
            {code('POST /api/v1/ml/retrain')} (admin only) - there is a 1-hour cooldown between
            manual retrains to prevent abuse. Retraining requires at least 100 telemetry readings
            in the training window; if a device has fewer, the model is skipped and the previous
            version is kept. After retraining, the new model is saved to{' '}
            {code('backend/ml/model.pkl')} and loaded into memory without restarting the backend.
          </>
        ),
      },
    ],
  },
  {
    title: 'Account and security',
    items: [
      {
        q: 'How do I set up two-factor authentication?',
        a: (
          <>
            Go to your <Link href="/profile" className="text-primary-400 hover:underline">profile page</Link>{' '}
            and click <strong>Enable 2FA</strong>. Scan the QR code with an authenticator app
            (Google Authenticator, Authy, 1Password etc.), then enter the 6-digit code to confirm.
            After enabling, every login requires a TOTP code after the password step. If you lose
            access to your authenticator, contact your administrator - there is no self-service
            2FA recovery yet. Admins can disable 2FA directly in the database.
          </>
        ),
      },
      {
        q: 'How do I reset my password?',
        a: (
          <>
            If you are logged in, go to your{' '}
            <Link href="/profile" className="text-primary-400 hover:underline">profile page</Link>{' '}
            and use the <strong>Change password</strong> section. If you are locked out after too
            many failed attempts, the account lock lifts automatically after 15 minutes. Admins can
            also clear the {code('locked_until')} column directly in the database. There is no
            self-service email password reset yet.
          </>
        ),
      },
      {
        q: 'How do I export or delete my account?',
        a: (
          <>
            Both options are on your{' '}
            <Link href="/profile" className="text-primary-400 hover:underline">profile page</Link>.
            <br /><br />
            <strong>Export</strong> - click <strong>Download my data</strong>. This downloads a
            JSON file containing your account details, all devices, telemetry history, alert
            history and tickets via {code('GET /api/v1/auth/me/export')}.
            <br /><br />
            <strong>Delete</strong> - scroll to <strong>Danger zone</strong> and click{' '}
            <strong>Delete account</strong>. This permanently removes your account, devices and
            telemetry readings. Ticket audit records are anonymised rather than deleted to preserve
            the audit trail. Export your data first - the action is irreversible.
          </>
        ),
      },
    ],
  },
  {
    title: 'Deployment and licensing',
    items: [
      {
        q: 'Can I self-host PHAEMOS?',
        a: (
          <>
            Yes - PHAEMOS is designed to be self-hosted. The recommended setup is a DigitalOcean
            VPS (Ubuntu 24.04, Docker Compose) for the backend, and Vercel for the Next.js frontend
            and MkDocs documentation site. A GitHub Student Pack provides ~$200 of DigitalOcean
            credit (~33 months at the $6/month Basic Droplet tier). See the{' '}
            <a
              href="https://docs.phaemos.com/deployment"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary-400 hover:underline"
            >
              deployment guide
            </a>{' '}
            for full step-by-step instructions including DNS, SSL, Nginx and Instatus status page
            setup.
          </>
        ),
      },
      {
        q: 'What does the AGPL-3.0 licence mean for me?',
        a: (
          <>
            PHAEMOS is licensed under the{' '}
            <a
              href="https://www.gnu.org/licenses/agpl-3.0.html"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary-400 hover:underline"
            >
              GNU Affero General Public License v3
            </a>.
            In plain terms: you can use, modify and distribute PHAEMOS freely, but if you run a
            modified version as a network service (i.e. users interact with it over the internet)
            you must publish your modifications under AGPL-3.0. If you are running it privately for
            your own machines with no external users, you do not need to publish anything. If you
            need a commercial licence without the AGPL obligations, contact{' '}
            <a href="mailto:contact@phaemos.com" className="text-primary-400 hover:underline">
              contact@phaemos.com
            </a>.
          </>
        ),
      },
    ],
  },
];

export default function FaqPage() {
  let globalIndex = 0;

  return (
    <div className="max-w-3xl mx-auto px-6 py-12 text-surface-800 dark:text-surface-200 space-y-10">
      <div className="space-y-2">
        <h1 className="text-3xl font-bold">FAQ</h1>
        <p className="text-surface-600 dark:text-surface-400">
          Frequently asked questions about PHAEMOS. Can&apos;t find what you need?{' '}
          <a
            href="https://github.com/zaccesss/phaemos/discussions"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary-400 hover:underline"
          >
            Ask in GitHub Discussions.
          </a>
        </p>
      </div>

      {FAQ_SECTIONS.map(({ title, items }) => (
        <section key={title} className="space-y-6">
          <h2 className="text-xl font-semibold border-b border-surface-200 dark:border-surface-800 pb-2">
            {title}
          </h2>
          <div className="space-y-6">
            {items.map(({ q, a }) => {
              globalIndex += 1;
              const n = globalIndex;
              return (
                <section key={q} className="space-y-2">
                  <h3 className="text-base font-semibold text-surface-900 dark:text-surface-50">
                    {n}. {q}
                  </h3>
                  <div className="text-surface-600 dark:text-surface-400 leading-relaxed text-sm">
                    {a}
                  </div>
                </section>
              );
            })}
          </div>
        </section>
      ))}

      <section className="rounded-xl border border-surface-200 dark:border-surface-800 p-5 space-y-2">
        <p className="font-semibold">Still have questions?</p>
        <p className="text-sm text-surface-600 dark:text-surface-400">
          Ask in{' '}
          <a
            href="https://github.com/zaccesss/phaemos/discussions"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary-400 hover:underline"
          >
            GitHub Discussions
          </a>
          , check the{' '}
          <Link href="/docs" className="text-primary-400 hover:underline">docs hub</Link>,
          or email{' '}
          <a href="mailto:support@phaemos.com" className="text-primary-400 hover:underline">
            support@phaemos.com
          </a>
          .
        </p>
      </section>
    </div>
  );
}
