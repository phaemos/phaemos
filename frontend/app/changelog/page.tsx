import { readFileSync } from 'fs';
import { join } from 'path';
import type { Metadata } from 'next';
import ReactMarkdown from 'react-markdown';

export const metadata: Metadata = {
  title: 'Changelog - PHAEMOS',
  description: 'Version history and release notes for PHAEMOS.',
};

// I read CHANGELOG.md at build time so the page stays static with zero runtime cost.
function getChangelog(): string {
  try {
    return readFileSync(join(process.cwd(), '..', 'CHANGELOG.md'), 'utf8');
  } catch {
    return '# Changelog\n\nChangelog not available.';
  }
}

export default function ChangelogPage() {
  const content = getChangelog();

  return (
    <main className="p-6 max-w-3xl mx-auto space-y-8">

      <section className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-widest text-surface-400 dark:text-surface-500">
          Changelog
        </p>
        <h1 className="text-3xl font-bold tracking-tight text-surface-900 dark:text-surface-50">
          Version history
        </h1>
        <p className="text-surface-600 dark:text-surface-400">
          All notable changes to PHAEMOS are documented here.
          Format follows{' '}
          <a
            href="https://keepachangelog.com/en/1.1.0/"
            target="_blank"
            rel="noopener noreferrer"
            className="text-brand-600 dark:text-brand-400 hover:underline"
          >
            Keep a Changelog
          </a>
          .
        </p>
      </section>

      <article className="card p-8 prose prose-sm max-w-none dark:prose-invert
        prose-headings:text-surface-900 dark:prose-headings:text-surface-50
        prose-headings:font-bold prose-headings:tracking-tight
        prose-h1:text-2xl prose-h2:text-xl prose-h2:mt-8 prose-h2:mb-3
        prose-h3:text-base prose-h3:mt-4 prose-h3:mb-2
        prose-p:text-surface-600 dark:prose-p:text-surface-400 prose-p:leading-relaxed
        prose-a:text-brand-600 dark:prose-a:text-brand-400 prose-a:no-underline hover:prose-a:underline
        prose-strong:text-surface-900 dark:prose-strong:text-surface-50
        prose-li:text-surface-600 dark:prose-li:text-surface-400
        prose-code:font-mono prose-code:text-xs
        prose-code:bg-surface-100 dark:prose-code:bg-surface-800
        prose-code:px-1 prose-code:rounded
        prose-hr:border-surface-200 dark:prose-hr:border-surface-800
        prose-ul:space-y-1"
      >
        <ReactMarkdown>{content}</ReactMarkdown>
      </article>

    </main>
  );
}
