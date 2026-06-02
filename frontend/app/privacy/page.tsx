import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Privacy Policy - PHAEMOS',
};

export default function PrivacyPage() {
  return (
    <div className="max-w-3xl mx-auto px-6 py-12 text-surface-800 dark:text-surface-200 space-y-8">
      <h1 className="text-3xl font-bold">Privacy Policy</h1>
      <p className="text-sm text-surface-500">Last updated: June 2026</p>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">1. Who we are</h2>
        <p>
          PHAEMOS is an IoT predictive maintenance platform developed as an academic project.
          References to &quot;we&quot;, &quot;us&quot; or &quot;our&quot; refer to the PHAEMOS project team.
          Contact: <a href="mailto:contact@phaemos.com" className="text-primary-400 hover:underline">contact@phaemos.com</a>
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">2. What data we collect</h2>
        <ul className="list-disc list-inside space-y-1 text-surface-600 dark:text-surface-400">
          <li><strong>Account data:</strong> name, email address, hashed password, phone number (optional).</li>
          <li><strong>Device data:</strong> device names, locations, API keys (stored as hashed values), telemetry readings from connected sensors.</li>
          <li><strong>Usage data:</strong> audit log entries (actions performed by admin users).</li>
          <li><strong>Cookies:</strong> an httpOnly cookie storing your refresh token for session management. A localStorage key storing your access token and theme preference.</li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">3. How we use your data</h2>
        <ul className="list-disc list-inside space-y-1 text-surface-600 dark:text-surface-400">
          <li>To provide and operate the PHAEMOS platform.</li>
          <li>To authenticate you and maintain your session.</li>
          <li>To send alert notifications when sensor thresholds are exceeded.</li>
          <li>To maintain an audit trail for administrative actions.</li>
        </ul>
        <p>We do not sell, rent, or share your personal data with third parties for marketing purposes.</p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">4. Data retention</h2>
        <p>
          Account data is retained until you delete your account. Telemetry data older than 90 days
          is automatically purged by a scheduled retention job. Audit log entries are retained
          for 1 year.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">5. Your rights (UK GDPR)</h2>
        <p>You have the right to:</p>
        <ul className="list-disc list-inside space-y-1 text-surface-600 dark:text-surface-400">
          <li><strong>Access</strong> — download a copy of all data we hold about you from your <a href="/profile" className="text-primary-400 hover:underline">profile page</a>.</li>
          <li><strong>Erasure</strong> — delete your account and all associated personal data from your profile page. Ticket audit records are anonymised, not deleted.</li>
          <li><strong>Rectification</strong> — update your name, email and phone number from your profile page.</li>
          <li><strong>Portability</strong> — export your data as a JSON file from your profile page.</li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">6. Cookies</h2>
        <p>
          We use one functional cookie: a <code className="text-xs bg-surface-100 dark:bg-surface-800 px-1 rounded">refresh_token</code> httpOnly
          cookie used solely to renew your session. This cookie is strictly necessary for the platform
          to function and does not require consent under UK GDPR. We do not use tracking, advertising,
          or analytics cookies.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">7. Security</h2>
        <p>
          Passwords are stored using bcrypt hashing. API keys are stored as SHA-256 hashes.
          All API traffic is served over HTTPS in production. JWT tokens are short-lived (15 minutes).
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">8. Changes to this policy</h2>
        <p>
          We may update this policy. The &quot;last updated&quot; date at the top will reflect any changes.
          Continued use of the platform after changes constitutes acceptance.
        </p>
      </section>

      <footer className="pt-8 border-t border-surface-200 dark:border-surface-800 text-xs text-surface-400">
        &copy; {new Date().getFullYear()} PHAEMOS. All rights reserved.
      </footer>
    </div>
  );
}
