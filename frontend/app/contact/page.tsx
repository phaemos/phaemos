import type { Metadata } from 'next';
import ContactForm from '@/components/ContactForm';

export const metadata: Metadata = {
  title: 'Contact - PHAEMOS',
  description: 'Get in touch with the PHAEMOS team for general enquiries, technical questions or feedback.',
};

export default function ContactPage() {
  return (
    <div className="max-w-2xl mx-auto px-6 py-12 space-y-8">
      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-widest text-surface-400 dark:text-surface-500">
          Get in touch
        </p>
        <h1 className="text-3xl font-bold tracking-tight text-surface-900 dark:text-surface-50">
          Contact us
        </h1>
        <p className="text-surface-600 dark:text-surface-400">
          Use this form for general enquiries and feedback. For bug reports and feature
          requests, open a{' '}
          <a
            href="https://github.com/zaccesss/phaemos/issues"
            target="_blank"
            rel="noopener noreferrer"
            className="text-brand-600 dark:text-brand-400 hover:underline"
          >
            GitHub issue
          </a>{' '}
          instead - it keeps things public and trackable.
        </p>
      </div>

      <ContactForm />

      <div className="border-t border-surface-200 dark:border-surface-800 pt-6 space-y-3 text-sm text-surface-500 dark:text-surface-400">
        <p>
          <span className="font-medium text-surface-700 dark:text-surface-300">Security issues</span>{' '}
          - do not use this form. See the{' '}
          <a href="/security" className="text-brand-600 dark:text-brand-400 hover:underline">
            security policy
          </a>{' '}
          for responsible disclosure instructions.
        </p>
        <p>
          <span className="font-medium text-surface-700 dark:text-surface-300">Support requests</span>{' '}
          - visit the{' '}
          <a href="/support" className="text-brand-600 dark:text-brand-400 hover:underline">
            support page
          </a>{' '}
          or email{' '}
          <a href="mailto:support@phaemos.com" className="text-brand-600 dark:text-brand-400 hover:underline">
            support@phaemos.com
          </a>
          .
        </p>
      </div>
    </div>
  );
}
