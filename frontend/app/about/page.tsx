import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'About - PHAEMOS',
  description: 'Open-source smart maintenance platform built to predict equipment failure before it happens.',
};

const STACK = [
  { layer: 'Frontend',  items: 'Next.js 15, React 18, Tailwind CSS, Recharts' },
  { layer: 'Backend',   items: 'FastAPI, SQLAlchemy, PostgreSQL, Redis' },
  { layer: 'ML',        items: 'scikit-learn Isolation Forest, NumPy' },
  { layer: 'Auth',      items: 'JWT (15-min access tokens), httpOnly refresh cookies, TOTP 2FA, Google OAuth, GitHub OAuth' },
  { layer: 'Firmware',  items: 'ESP32 (Arduino), STM32F411 (CMSIS-DSP FFT), Raspberry Pi Pico W, Arduino Nano' },
  { layer: 'Sensors',   items: 'DHT22, MPU-6050, INA219, ACS712, BMP280, MQ-135, HC-SR04, LM35, IR sensor' },
  { layer: 'Ops',       items: 'Docker Compose, GitHub Actions CI, Prometheus + Grafana monitoring' },
];

const DIFFERENTIATORS = [
  {
    title: 'FFT vibration analysis',
    body: '128-point real FFT runs on the STM32 node via CMSIS-DSP, extracting the dominant frequency from accelerometer data. Bearing faults produce characteristic frequency signatures that simple threshold rules miss.',
  },
  {
    title: 'Isolation Forest ML',
    body: 'Instead of static thresholds, an Isolation Forest model learns what normal looks like for each device and raises an anomaly score when readings deviate. No labelled failure data needed.',
  },
  {
    title: 'Built-in ticket workflow',
    body: 'Alerts connect directly to a ticket system with priority, assignment and status tracking. Nothing gets lost in a notification feed. Alerts create tickets in one click.',
  },
  {
    title: 'Multi-tenant RBAC',
    body: 'Admin and technician roles with device-level ownership. Admins manage the fleet; technicians see only the devices assigned to them. Per-user permission overrides available.',
  },
  {
    title: 'Real hardware',
    body: 'Four firmware nodes, four PCBs, eleven sensors. This is not a demo against a simulator - every feature was built against physical hardware with real sensor data.',
  },
  {
    title: 'Open source',
    body: 'Apache 2.0 licensed. Fork it, deploy it, contribute. The architecture is intentionally simple - one Docker Compose file stands up the entire stack.',
  },
];

export default function AboutPage() {
  return (
    <main className="p-6 max-w-4xl mx-auto space-y-12">

      {/* Hero */}
      <section className="space-y-4">
        <p className="text-xs font-semibold uppercase tracking-widest text-surface-400 dark:text-surface-500">
          About PHAEMOS
        </p>
        <h1 className="text-3xl font-bold tracking-tight text-surface-900 dark:text-surface-50">
          Built for real hardware,<br />open for everyone.
        </h1>
        <p className="text-lg text-surface-600 dark:text-surface-400 max-w-2xl">
          PHAEMOS is an open-source smart maintenance platform that uses FFT vibration analysis
          and machine learning to predict equipment failure before it happens.
        </p>
      </section>

      {/* Mission */}
      <section className="card p-6 space-y-3">
        <h2 className="text-xl font-bold tracking-tight text-surface-900 dark:text-surface-50">Mission</h2>
        <p className="text-surface-600 dark:text-surface-400 leading-relaxed">
          Most maintenance systems are reactive - a machine fails, someone notices, a ticket gets filed.
          PHAEMOS measures equipment continuously, models what normal looks like, and raises an alert
          the moment readings drift out of range. The goal is to catch failures before they cascade,
          not after.
        </p>
        <p className="text-surface-600 dark:text-surface-400 leading-relaxed">
          The platform was designed to be the right size: lighter than ThingsBoard, more structured than
          Node-RED, and with the workflow layer that Grafana lacks - all running on a single
          <code className="font-mono text-sm bg-surface-100 dark:bg-surface-800 px-1 rounded">docker compose up</code>.
        </p>
      </section>

      {/* What makes it different */}
      <section className="space-y-4">
        <h2 className="text-xl font-bold tracking-tight text-surface-900 dark:text-surface-50">What makes it different</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {DIFFERENTIATORS.map(({ title, body }) => (
            <div key={title} className="card p-5 space-y-2">
              <h3 className="font-semibold text-surface-900 dark:text-surface-50">{title}</h3>
              <p className="text-sm text-surface-600 dark:text-surface-400 leading-relaxed">{body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Architecture overview */}
      <section className="card p-6 space-y-3">
        <h2 className="text-xl font-bold tracking-tight text-surface-900 dark:text-surface-50">Architecture overview</h2>
        <p className="text-surface-600 dark:text-surface-400 leading-relaxed">
          Firmware nodes report telemetry every 5 seconds via HTTP POST. The FastAPI backend stores
          readings in PostgreSQL, runs Isolation Forest scoring, evaluates alert rules, and pushes
          live updates to the frontend over WebSocket. The Next.js frontend renders real-time sensor
          grids, Recharts telemetry charts, and the ticket workflow. Redis handles session state and
          background task queuing.
        </p>
        <a
          href="https://github.com/zaccesss/phaemos/blob/main/docs/architecture.md"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-sm text-brand-600 dark:text-brand-400 hover:underline"
        >
          Full architecture document
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
          </svg>
        </a>
      </section>

      {/* Tech stack */}
      <section className="space-y-4">
        <h2 className="text-xl font-bold tracking-tight text-surface-900 dark:text-surface-50">Tech stack</h2>
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <tbody>
              {STACK.map(({ layer, items }, i) => (
                <tr
                  key={layer}
                  className={i % 2 === 0 ? 'bg-surface-50 dark:bg-surface-900' : 'bg-white dark:bg-surface-800'}
                >
                  <td className="px-4 py-3 font-medium text-surface-900 dark:text-surface-50 w-28 shrink-0">
                    {layer}
                  </td>
                  <td className="px-4 py-3 text-surface-600 dark:text-surface-400 font-mono text-xs">
                    {items}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Contact */}
      <section className="card p-6 space-y-3">
        <h2 className="text-xl font-bold tracking-tight text-surface-900 dark:text-surface-50">Get in touch</h2>
        <div className="flex flex-col sm:flex-row gap-4 text-sm">
          <a
            href="https://github.com/zaccesss/phaemos"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 text-surface-600 dark:text-surface-400 hover:text-brand-600 dark:hover:text-brand-400 transition-colors"
          >
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 0C5.37 0 0 5.37 0 12c0 5.3 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 21.795 24 17.295 24 12c0-6.63-5.37-12-12-12" />
            </svg>
            GitHub
          </a>
          <a
            href="mailto:hello@phaemos.com"
            className="flex items-center gap-2 text-surface-600 dark:text-surface-400 hover:text-brand-600 dark:hover:text-brand-400 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
            </svg>
            hello@phaemos.com
          </a>
          <a
            href="mailto:contact@phaemos.com"
            className="flex items-center gap-2 text-surface-600 dark:text-surface-400 hover:text-brand-600 dark:hover:text-brand-400 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            General enquiries: contact@phaemos.com
          </a>
        </div>
      </section>

    </main>
  );
}
