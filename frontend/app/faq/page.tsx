import type { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'FAQ - PHAEMOS',
  description: 'Frequently asked questions about PHAEMOS - devices, sensors, alerts, ML, account management and the API.',
};

const FAQS = [
  {
    q: 'How do I add a device?',
    a: (
      <>
        Go to the <Link href="/devices" className="text-primary-400 hover:underline">Devices</Link> page
        and click <strong>Add device</strong>. Give the device a name and an optional description.
        Once created, copy the generated API key and set it as the <code className="text-xs bg-surface-100 dark:bg-surface-800 px-1 rounded">PHAEMOS_API_KEY</code> environment
        variable on your firmware node. The device will appear as online within seconds of the first
        telemetry POST.
      </>
    ),
  },
  {
    q: 'What sensors are supported?',
    a: (
      <>
        PHAEMOS reads 11 sensor channels across 4 firmware nodes:{' '}
        <strong>temperature</strong> (DHT22, LM35),{' '}
        <strong>humidity</strong> (DHT22),{' '}
        <strong>air quality</strong> (MQ-135),{' '}
        <strong>vibration X/Y/Z + FFT peak frequency</strong> (MPU-6050 + STM32 CMSIS-DSP),{' '}
        <strong>current and voltage</strong> (INA219, ACS712),{' '}
        <strong>pressure</strong> (BMP280),{' '}
        <strong>distance</strong> (HC-SR04), and{' '}
        <strong>IR presence</strong>. See the{' '}
        <a
          href="https://github.com/zaccesss/phaemos/blob/main/docs/sensor_reference.md"
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary-400 hover:underline"
        >
          sensor reference
        </a>{' '}
        for wiring tables and calibration notes.
      </>
    ),
  },
  {
    q: 'How do alerts work?',
    a: (
      <>
        Alert rules define a sensor channel, a comparison operator (above/below/equals), and a
        threshold value. Every time a telemetry reading is stored the backend evaluates all active
        rules for that device. When a rule fires an{' '}
        <Link href="/alerts" className="text-primary-400 hover:underline">Alert</Link> is created,
        a webhook notification is dispatched (if configured), and an SMS is sent if the severity is
        critical. Alerts stay open until you mark them resolved. You can create a ticket from any
        alert in one click.
      </>
    ),
  },
  {
    q: 'What is the ML anomaly score?',
    a: (
      <>
        The anomaly score is produced by an Isolation Forest model trained on the last 30 days of
        normal telemetry for each device. Scores range from roughly -0.5 (highly anomalous) to +0.5
        (typical). A score below -0.1 is treated as anomalous and triggers an ML alert. The model
        uses 7 feature columns: temperature, vibration X/Y/Z, FFT peak frequency, current and
        voltage. It is retrained automatically when you call{' '}
        <code className="text-xs bg-surface-100 dark:bg-surface-800 px-1 rounded">POST /api/v1/ml/retrain</code>{' '}
        (admin only, 1-hour cooldown). See the{' '}
        <Link href="/blog/isolation-forest-anomaly-detection" className="text-primary-400 hover:underline">
          blog post on anomaly detection
        </Link>{' '}
        for a full explanation.
      </>
    ),
  },
  {
    q: 'How do I reset my password?',
    a: (
      <>
        If you are logged in, go to your{' '}
        <Link href="/profile" className="text-primary-400 hover:underline">profile page</Link>{' '}
        and use the <strong>Change password</strong> section. Enter your current password and a new
        one. If you are locked out, contact your administrator - there is no self-service password
        reset by email yet. Admins can reset the <code className="text-xs bg-surface-100 dark:bg-surface-800 px-1 rounded">locked_until</code>{' '}
        column directly in the database.
      </>
    ),
  },
  {
    q: 'How do I export my data?',
    a: (
      <>
        From your{' '}
        <Link href="/profile" className="text-primary-400 hover:underline">profile page</Link>,
        click <strong>Download my data</strong>. This calls{' '}
        <code className="text-xs bg-surface-100 dark:bg-surface-800 px-1 rounded">GET /api/v1/auth/me/export</code>{' '}
        and downloads a JSON file containing your account details, devices, telemetry readings,
        alert history and tickets. Admins can also export the full audit log as a signed CSV from
        the Admin panel.
      </>
    ),
  },
  {
    q: 'How do I delete my account?',
    a: (
      <>
        Go to your{' '}
        <Link href="/profile" className="text-primary-400 hover:underline">profile page</Link>{' '}
        and scroll to <strong>Danger zone</strong>. Click <strong>Delete account</strong> and confirm.
        This permanently deletes your account, devices and telemetry. Ticket audit records are
        anonymised rather than deleted to preserve the audit trail. The action is irreversible -
        export your data first if you want a copy.
      </>
    ),
  },
  {
    q: 'What is the API key used for?',
    a: (
      <>
        Each device has a unique API key used by the firmware node to authenticate telemetry POSTs.
        The key is sent in the <code className="text-xs bg-surface-100 dark:bg-surface-800 px-1 rounded">X-API-Key</code> header.
        It is stored as a SHA-256 hash - the plaintext is only shown once at creation. If you lose
        it, rotate it from the device detail page. The API key is separate from the user JWT - it
        is only valid for telemetry ingestion, not for any other API endpoint.
      </>
    ),
  },
];

export default function FaqPage() {
  return (
    <div className="max-w-3xl mx-auto px-6 py-12 text-surface-800 dark:text-surface-200 space-y-8">
      <h1 className="text-3xl font-bold">FAQ</h1>
      <p className="text-surface-600 dark:text-surface-400">
        Frequently asked questions about PHAEMOS. Can&apos;t find what you need?{' '}
        <Link href="/support" className="text-primary-400 hover:underline">Contact support.</Link>
      </p>

      <div className="space-y-6">
        {FAQS.map(({ q, a }, i) => (
          <section key={q} className="space-y-2">
            <h2 className="text-lg font-semibold">
              {i + 1}. {q}
            </h2>
            <p className="text-surface-600 dark:text-surface-400 leading-relaxed">{a}</p>
          </section>
        ))}
      </div>

      <section className="rounded-xl border border-surface-200 dark:border-surface-800 p-5 space-y-2">
        <p className="font-semibold">Still have questions?</p>
        <p className="text-sm text-surface-600 dark:text-surface-400">
          Check the{' '}
          <Link href="/docs" className="text-primary-400 hover:underline">docs hub</Link>,
          open a{' '}
          <a
            href="https://github.com/zaccesss/phaemos/issues"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary-400 hover:underline"
          >
            GitHub issue
          </a>
          , or email{' '}
          <a href="mailto:support@phaemos.com" className="text-primary-400 hover:underline">
            support@phaemos.com
          </a>
          .
        </p>
      </section>
    </div>
  );
}
