import type { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Security Policy - PHAEMOS',
  description: 'Security policy, responsible disclosure instructions and implemented security controls for PHAEMOS.',
};

const CONTROLS = [
  { area: 'Authentication',   items: ['JWT access tokens (15-min expiry, HS256)', 'httpOnly refresh cookie with silent renewal', 'Bcrypt password hashing (passlib, cost 12)', 'Password strength enforcement (8+ chars, uppercase, digit)'] },
  { area: 'Authorisation',    items: ['Role-based access control (admin / technician / viewer)', 'Per-user permission overrides via RBAC permissions column', 'Device-level ownership (technicians see only their devices)', 'Admin-only guards on all mutating routes'] },
  { area: '2FA and OAuth',    items: ['TOTP 2FA (RFC 6238 via pyotp, 30s window)', 'Google and GitHub OAuth via authlib', 'Backup codes not yet implemented - planned'] },
  { area: 'Brute force',      items: ['Rate limiting on POST /auth/login (5 requests/min via slowapi)', '15-minute account lockout after 5 consecutive failures', 'WebSocket closes with code 1008 on invalid JWT - client does not retry'] },
  { area: 'Transport',        items: ['CORS locked to explicit origin list (no wildcard)', 'HTTPS enforced in production via Vercel/reverse proxy', 'Strict-Transport-Security header set'] },
  { area: 'Headers',          items: ['X-Frame-Options: DENY', 'X-Content-Type-Options: nosniff', 'Referrer-Policy: strict-origin-when-cross-origin', 'Content-Security-Policy (report-only in development)'] },
  { area: 'Data',             items: ['API keys stored as SHA-256 hashes (never plaintext)', 'SQLAlchemy parameterised queries throughout (no string interpolation)', 'Audit log on all mutating routes with actor, action, target, timestamp', 'GDPR data export (JSON) and account deletion available from profile page'] },
  { area: 'Infrastructure',   items: ['Firmware upload capped at 2 MB', 'Redis session state behind private network', 'robots.txt disallows all crawlers', 'Sitemap excludes authenticated routes'] },
];

export default function SecurityPage() {
  return (
    <div className="max-w-3xl mx-auto px-6 py-12 text-surface-800 dark:text-surface-200 space-y-8">
      <h1 className="text-3xl font-bold">Security Policy</h1>
      <p className="text-sm text-surface-500">Last updated: June 2026</p>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">1. Responsible disclosure</h2>
        <p>
          If you discover a security vulnerability in PHAEMOS, please do not open a public GitHub issue.
          Report it privately via{' '}
          <a
            href="https://github.com/zaccesss/phaemos/security/advisories/new"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary-400 hover:underline"
          >
            GitHub Security Advisories
          </a>
          . You can also email{' '}
          <a href="mailto:dev@phaemos.com" className="text-primary-400 hover:underline">
            dev@phaemos.com
          </a>{' '}
          with the subject line &quot;Security disclosure&quot;.
        </p>
        <p>
          Please include: a description of the vulnerability, steps to reproduce, and the potential
          impact. We aim to respond within 5 working days and will keep you informed as we investigate
          and resolve the issue.
        </p>
        <p>
          We ask that you do not disclose the vulnerability publicly until we have had a reasonable
          opportunity to address it.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">2. Scope</h2>
        <p>The following are in scope for responsible disclosure:</p>
        <ul className="list-disc list-inside space-y-1 text-surface-600 dark:text-surface-400">
          <li>Authentication and session management flaws</li>
          <li>Authorisation bypasses (accessing another user&apos;s data or admin functionality)</li>
          <li>Injection vulnerabilities (SQL, command, template)</li>
          <li>Cross-site scripting (XSS) or CSRF in the frontend</li>
          <li>Insecure direct object references</li>
          <li>Sensitive data exposure</li>
        </ul>
        <p className="text-surface-600 dark:text-surface-400">
          Out of scope: denial-of-service attacks, brute-force attacks against the rate limiter,
          and vulnerabilities in third-party dependencies that are already publicly known.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">3. Implemented security controls</h2>
        <p className="text-surface-600 dark:text-surface-400">
          The full security control record is maintained in{' '}
          <a
            href="https://github.com/zaccesss/phaemos/blob/main/docs/security.md"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary-400 hover:underline"
          >
            docs/security.md
          </a>
          . A summary by area is below.
        </p>

        <div className="space-y-4 mt-2">
          {CONTROLS.map(({ area, items }) => (
            <div key={area} className="rounded-xl border border-surface-200 dark:border-surface-800 overflow-hidden">
              <div className="px-4 py-2 bg-surface-100 dark:bg-surface-800 font-semibold text-sm text-surface-900 dark:text-surface-50">
                {area}
              </div>
              <ul className="px-4 py-3 space-y-1">
                {items.map((item) => (
                  <li key={item} className="flex items-start gap-2 text-sm text-surface-600 dark:text-surface-400">
                    <span className="mt-1 w-1.5 h-1.5 rounded-full bg-success-500 shrink-0" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">4. Known limitations</h2>
        <ul className="list-disc list-inside space-y-1 text-surface-600 dark:text-surface-400">
          <li>
            JWT tokens are stored in both localStorage and a cookie. The cookie is not httpOnly
            because the Next.js edge middleware reads it at the JS layer. This is a known trade-off
            documented in{' '}
            <a
              href="https://github.com/zaccesss/phaemos/blob/main/docs/security.md"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary-400 hover:underline"
            >
              docs/security.md
            </a>
            .
          </li>
          <li>Apple OAuth is a planned but not yet implemented.</li>
          <li>Backup codes for TOTP are planned but not yet implemented.</li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">5. Contact</h2>
        <p>
          For security disclosures:{' '}
          <a
            href="https://github.com/zaccesss/phaemos/security/advisories/new"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary-400 hover:underline"
          >
            GitHub Security Advisories
          </a>{' '}
          or{' '}
          <a href="mailto:dev@phaemos.com" className="text-primary-400 hover:underline">
            dev@phaemos.com
          </a>
          .<br />
          For general support, see the{' '}
          <Link href="/support" className="text-primary-400 hover:underline">
            support page
          </Link>
          .
        </p>
      </section>
    </div>
  );
}
