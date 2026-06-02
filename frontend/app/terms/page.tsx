import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Terms of Service - PHAEMOS',
};

export default function TermsPage() {
  return (
    <div className="max-w-3xl mx-auto px-6 py-12 text-surface-800 dark:text-surface-200 space-y-8">
      <h1 className="text-3xl font-bold">Terms of Service</h1>
      <p className="text-sm text-surface-500">Last updated: June 2026</p>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">1. Acceptance</h2>
        <p>
          By accessing or using PHAEMOS, you agree to be bound by these Terms of Service.
          If you do not agree, do not use the platform.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">2. Description of service</h2>
        <p>
          PHAEMOS is an IoT predictive maintenance platform that ingests telemetry data from
          connected sensors, applies machine learning anomaly detection, generates alerts,
          and provides a maintenance ticketing workflow. The platform is provided as an
          academic portfolio project.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">3. Acceptable use</h2>
        <p>You agree not to:</p>
        <ul className="list-disc list-inside space-y-1 text-surface-600 dark:text-surface-400">
          <li>Use the platform to store, transmit, or process illegal content.</li>
          <li>Attempt to circumvent authentication, rate limiting, or access controls.</li>
          <li>Use the platform in a way that degrades service for other users.</li>
          <li>Reverse-engineer or extract proprietary components of the platform.</li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">4. Account responsibilities</h2>
        <p>
          You are responsible for maintaining the security of your account credentials.
          You must notify us immediately at <a href="mailto:contact@phaemos.com" className="text-primary-400 hover:underline">contact@phaemos.com</a> if
          you suspect unauthorised access to your account.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">5. Data and privacy</h2>
        <p>
          Your use of PHAEMOS is also governed by our{' '}
          <a href="/privacy" className="text-primary-400 hover:underline">Privacy Policy</a>,
          which is incorporated into these Terms by reference.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">6. Disclaimers</h2>
        <p>
          PHAEMOS is provided &quot;as is&quot; without warranty of any kind. We do not guarantee
          uninterrupted availability or freedom from errors. The platform is an academic project
          and should not be used as the sole monitoring system in safety-critical environments.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">7. Limitation of liability</h2>
        <p>
          To the fullest extent permitted by applicable law, we shall not be liable for
          any indirect, incidental, special, or consequential damages arising from your
          use of or inability to use the platform.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">8. Governing law</h2>
        <p>
          These Terms are governed by the laws of England and Wales.
          Any disputes shall be subject to the exclusive jurisdiction of the courts of England and Wales.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">9. Changes</h2>
        <p>
          We may update these Terms. The &quot;last updated&quot; date above will reflect changes.
          Continued use of the platform after changes constitutes acceptance of the updated Terms.
        </p>
      </section>

      <footer className="pt-8 border-t border-surface-200 dark:border-surface-800 text-xs text-surface-400">
        &copy; {new Date().getFullYear()} PHAEMOS. All rights reserved.
      </footer>
    </div>
  );
}
