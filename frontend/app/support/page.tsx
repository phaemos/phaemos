import type { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Support - PHAEMOS',
  description: 'Support resources for PHAEMOS - documentation, GitHub issues, contact and troubleshooting.',
};

const TROUBLESHOOTING = [
  {
    problem: 'Backend crashes on startup after docker compose down',
    solution: 'The postgres data volume is wiped by docker compose down. Use docker compose stop to preserve data between restarts. After a wipe, re-seed with make seed.',
  },
  {
    problem: 'Login blocked after 5 failed attempts',
    solution: 'The account is locked for 15 minutes. Wait it out, or ask an admin to reset the locked_until column in the database directly.',
  },
  {
    problem: 'Frontend shows blank screen after fresh clone',
    solution: 'Ensure frontend/.env.local contains NEXT_PUBLIC_API_URL=http://localhost:8000. Run: echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > frontend/.env.local',
  },
  {
    problem: 'WebSocket not connecting',
    solution: 'Verify the backend is running and NEXT_PUBLIC_API_URL is set correctly. The WebSocket URL is derived from NEXT_PUBLIC_API_URL by replacing http with ws. Check browser devtools for the WS connection URL.',
  },
  {
    problem: 'Telemetry not appearing for a device',
    solution: 'Confirm the firmware node is sending the correct API key in the X-API-Key header, and that the device ID in the POST path matches the device ID shown on the device detail page.',
  },
  {
    problem: 'Rate limit error on login',
    solution: 'The login endpoint is capped at 5 requests per minute per IP. If running behind a reverse proxy, ensure FORWARDED_ALLOW_IPS is set in the backend environment so the real client IP is used, not the proxy IP.',
  },
];

export default function SupportPage() {
  return (
    <div className="max-w-3xl mx-auto px-6 py-12 text-surface-800 dark:text-surface-200 space-y-8">
      <h1 className="text-3xl font-bold">Support</h1>
      <p className="text-surface-600 dark:text-surface-400">
        PHAEMOS is an independent project. Support is best-effort with no guaranteed response time.
      </p>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold">1. Get help</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">

          <a
            href="https://github.com/zaccesss/phaemos/issues"
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-xl border border-surface-200 dark:border-surface-800 p-4 hover:border-primary-500 transition-colors space-y-1"
          >
            <p className="font-semibold text-surface-900 dark:text-surface-50">GitHub Issues</p>
            <p className="text-sm text-surface-600 dark:text-surface-400">
              Bug reports and feature requests. Use a template - it speeds up triage.
            </p>
          </a>

          <a
            href="mailto:support@phaemos.com"
            className="rounded-xl border border-surface-200 dark:border-surface-800 p-4 hover:border-primary-500 transition-colors space-y-1"
          >
            <p className="font-semibold text-surface-900 dark:text-surface-50">Email support</p>
            <p className="text-sm text-surface-600 dark:text-surface-400">
              support@phaemos.com - for questions that should not be public.
              Aim to reply within 5 working days.
            </p>
          </a>

          <Link
            href="/contact"
            className="rounded-xl border border-surface-200 dark:border-surface-800 p-4 hover:border-primary-500 transition-colors space-y-1"
          >
            <p className="font-semibold text-surface-900 dark:text-surface-50">Contact form</p>
            <p className="text-sm text-surface-600 dark:text-surface-400">
              Send a message via the contact page for general enquiries and feedback.
            </p>
          </Link>

          <Link
            href="/docs"
            className="rounded-xl border border-surface-200 dark:border-surface-800 p-4 hover:border-primary-500 transition-colors space-y-1"
          >
            <p className="font-semibold text-surface-900 dark:text-surface-50">Documentation</p>
            <p className="text-sm text-surface-600 dark:text-surface-400">
              Architecture, API reference, sensor wiring, deployment guide and more.
            </p>
          </Link>

          <Link
            href="/faq"
            className="rounded-xl border border-surface-200 dark:border-surface-800 p-4 hover:border-primary-500 transition-colors space-y-1"
          >
            <p className="font-semibold text-surface-900 dark:text-surface-50">FAQ</p>
            <p className="text-sm text-surface-600 dark:text-surface-400">
              Answers to the most common questions about devices, sensors, alerts and accounts.
            </p>
          </Link>
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold">2. Self-service resources</h2>
        <ul className="list-disc list-inside space-y-2 text-surface-600 dark:text-surface-400">
          <li>
            <a
              href="https://github.com/zaccesss/phaemos/blob/main/README.md"
              target="_blank" rel="noopener noreferrer"
              className="text-primary-400 hover:underline"
            >README.md</a>{' '}
            - project overview and quick start
          </li>
          <li>
            <a
              href="https://github.com/zaccesss/phaemos/blob/main/docs/deployment.md"
              target="_blank" rel="noopener noreferrer"
              className="text-primary-400 hover:underline"
            >docs/deployment.md</a>{' '}
            - full Docker Compose deployment guide
          </li>
          <li>
            <a
              href="https://github.com/zaccesss/phaemos/blob/main/docs/api-reference.md"
              target="_blank" rel="noopener noreferrer"
              className="text-primary-400 hover:underline"
            >docs/api-reference.md</a>{' '}
            - all REST endpoints and authentication requirements
          </li>
          <li>
            <a
              href="https://github.com/zaccesss/phaemos/blob/main/docs/sensor_reference.md"
              target="_blank" rel="noopener noreferrer"
              className="text-primary-400 hover:underline"
            >docs/sensor_reference.md</a>{' '}
            - sensor wiring tables and data dictionary
          </li>
          <li>
            <code className="text-xs bg-surface-100 dark:bg-surface-800 px-1 rounded">http://localhost:8000/docs</code>{' '}
            - interactive Swagger UI when the backend is running locally
          </li>
        </ul>
      </section>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold">3. Common troubleshooting</h2>
        <div className="space-y-4">
          {TROUBLESHOOTING.map(({ problem, solution }) => (
            <div key={problem} className="rounded-xl border border-surface-200 dark:border-surface-800 overflow-hidden">
              <div className="px-4 py-3 bg-surface-100 dark:bg-surface-800 font-medium text-sm text-surface-900 dark:text-surface-50">
                {problem}
              </div>
              <p className="px-4 py-3 text-sm text-surface-600 dark:text-surface-400 leading-relaxed">
                {solution}
              </p>
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">4. Security issues</h2>
        <p className="text-surface-600 dark:text-surface-400">
          Do not open a public issue for security vulnerabilities. See the{' '}
          <Link href="/security" className="text-primary-400 hover:underline">security policy</Link>{' '}
          for responsible disclosure instructions.
        </p>
      </section>
    </div>
  );
}
