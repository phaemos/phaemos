import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Docs - PHAEMOS',
  description: 'Documentation hub for PHAEMOS - architecture, API reference, deployment, security and more.',
};

const BASE = 'https://github.com/zaccesss/phaemos/blob/main/docs';

const SECTIONS = [
  {
    title: 'Architecture',
    description: 'System overview, component diagram, data flow from firmware nodes through FastAPI to the frontend.',
    href: `${BASE}/architecture.md`,
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
      </svg>
    ),
  },
  {
    title: 'API Reference',
    description: 'All REST endpoints, authentication requirements, request/response schemas, and WebSocket protocol.',
    href: `${BASE}/api-reference.md`,
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5" />
      </svg>
    ),
  },
  {
    title: 'Sensor Reference',
    description: 'Sensor specifications, wiring tables, calibration notes and measurement ranges for all 11 sensors.',
    href: `${BASE}/sensor_reference.md`,
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 14.25v2.25m3-4.5v4.5m3-6.75v6.75m3-9v9M6 20.25h12A2.25 2.25 0 0020.25 18V6A2.25 2.25 0 0018 3.75H6A2.25 2.25 0 003.75 6v12A2.25 2.25 0 006 20.25z" />
      </svg>
    ),
  },
  {
    title: 'Security',
    description: '18-measure security control table covering JWT, TOTP 2FA, OAuth, rate limiting, RBAC and more.',
    href: `${BASE}/security.md`,
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
      </svg>
    ),
  },
  {
    title: 'Deployment',
    description: 'Docker Compose setup, environment variables, database migrations, Vercel deployment and DNS configuration.',
    href: `${BASE}/deployment.md`,
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z" />
      </svg>
    ),
  },
  {
    title: 'Verification',
    description: 'Feature verification checklist - all implemented capabilities with test evidence.',
    href: `${BASE}/VERIFICATION.md`,
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  {
    title: 'Decisions',
    description: 'Architecture Decision Records (ADRs) explaining major design choices and the rationale behind them.',
    href: `${BASE}/decisions.md`,
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9 5.25h.008v.008H12v-.008z" />
      </svg>
    ),
  },
  {
    title: 'Schema',
    description: 'Database schema ER diagram, table definitions, and migration history.',
    href: `${BASE}/schema.md`,
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 2.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" />
      </svg>
    ),
  },
];

const QUICK_LINKS = [
  { label: 'GitHub repository', href: 'https://github.com/zaccesss/phaemos' },
  { label: 'Open an issue', href: 'https://github.com/zaccesss/phaemos/issues/new/choose' },
  { label: 'CHANGELOG', href: '/changelog' },
  { label: 'Status page', href: '/status' },
];

export default function DocsPage() {
  return (
    <main className="p-6 max-w-4xl mx-auto space-y-10">

      <section className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-widest text-surface-400 dark:text-surface-500">
          Documentation
        </p>
        <h1 className="text-3xl font-bold tracking-tight text-surface-900 dark:text-surface-50">
          PHAEMOS Docs
        </h1>
        <p className="text-surface-600 dark:text-surface-400">
          Architecture, API reference, deployment guide and more. All docs live in the{' '}
          <code className="font-mono text-sm bg-surface-100 dark:bg-surface-800 px-1 rounded">docs/</code>{' '}
          folder of the repository.
        </p>
      </section>

      {/* Doc cards */}
      <section>
        <p className="text-xs font-semibold uppercase tracking-widest text-surface-400 dark:text-surface-500 mb-4">
          All documents
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {SECTIONS.map(({ title, description, href, icon }) => (
            <a
              key={title}
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="card p-5 flex items-start gap-4 hover:shadow-md hover:-translate-y-0.5 transition-all duration-200 group"
            >
              <span className="mt-0.5 text-brand-600 dark:text-brand-400 shrink-0">
                {icon}
              </span>
              <div className="min-w-0">
                <h3 className="font-semibold text-surface-900 dark:text-surface-50 group-hover:text-brand-600 dark:group-hover:text-brand-400 transition-colors mb-1">
                  {title}
                </h3>
                <p className="text-sm text-surface-600 dark:text-surface-400 leading-relaxed">
                  {description}
                </p>
              </div>
            </a>
          ))}
        </div>
      </section>

      {/* Quick links */}
      <section className="card p-6 space-y-3">
        <h2 className="font-semibold text-surface-900 dark:text-surface-50">Quick links</h2>
        <div className="flex flex-wrap gap-3">
          {QUICK_LINKS.map(({ label, href }) => (
            <a
              key={label}
              href={href}
              target={href.startsWith('http') ? '_blank' : undefined}
              rel={href.startsWith('http') ? 'noopener noreferrer' : undefined}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium
                bg-surface-100 dark:bg-surface-800 text-surface-700 dark:text-surface-300
                hover:bg-surface-200 dark:hover:bg-surface-700 transition-colors"
            >
              {label}
              {href.startsWith('http') && (
                <svg className="w-3 h-3 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                </svg>
              )}
            </a>
          ))}
        </div>
      </section>

      {/* Support */}
      <section className="card p-6 space-y-2">
        <h2 className="font-semibold text-surface-900 dark:text-surface-50">Need help?</h2>
        <p className="text-sm text-surface-600 dark:text-surface-400">
          For bug reports and feature requests, open a{' '}
          <a
            href="https://github.com/zaccesss/phaemos/issues"
            target="_blank"
            rel="noopener noreferrer"
            className="text-brand-600 dark:text-brand-400 hover:underline"
          >
            GitHub issue
          </a>
          . For general questions and support, email{' '}
          <a href="mailto:support@phaemos.com" className="text-brand-600 dark:text-brand-400 hover:underline">
            support@phaemos.com
          </a>
          . For technical and developer enquiries, email{' '}
          <a href="mailto:dev@phaemos.com" className="text-brand-600 dark:text-brand-400 hover:underline">
            dev@phaemos.com
          </a>
          .
        </p>
      </section>

    </main>
  );
}
