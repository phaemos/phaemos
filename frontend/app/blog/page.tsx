import type { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Blog - PHAEMOS',
  description: 'Updates, technical deep dives and announcements from the PHAEMOS project.',
};

const POSTS = [
  {
    slug: 'introducing-phaemos',
    title: 'Introducing PHAEMOS - Predict Failure Before It Happens',
    date: '2026-05-01',
    excerpt: 'PHAEMOS is an open-source smart maintenance platform that uses vibration FFT analysis and machine learning to catch equipment failure before it disrupts operations.',
    tags: ['announcement', 'overview'],
  },
  {
    slug: 'isolation-forest-anomaly-detection',
    title: 'How Isolation Forest Powers PHAEMOS Anomaly Detection',
    date: '2026-05-15',
    excerpt: 'Isolation Forest spots equipment anomalies without needing labelled failure data - here is how it works in PHAEMOS and when to retrain the model.',
    tags: ['ml', 'technical'],
  },
  {
    slug: 'hardware-deep-dive',
    title: 'Hardware Deep Dive: 4 Nodes, 11 Sensors, One Platform',
    date: '2026-05-28',
    excerpt: 'A tour of the four firmware nodes at the core of PHAEMOS - ESP32 telemetry hub, STM32 vibration processor, Pico W power monitor, and Arduino Nano legacy bridge.',
    tags: ['hardware', 'firmware'],
  },
];

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
}

export default function BlogPage() {
  return (
    <main className="p-6 max-w-3xl mx-auto space-y-8">

      <section className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-widest text-surface-400 dark:text-surface-500">
          Blog
        </p>
        <h1 className="text-3xl font-bold tracking-tight text-surface-900 dark:text-surface-50">
          Updates and deep dives
        </h1>
        <p className="text-surface-600 dark:text-surface-400">
          Technical write-ups, feature announcements and hardware notes from the PHAEMOS project.
        </p>
      </section>

      <div className="space-y-4">
        {POSTS.map((post) => (
          <Link
            key={post.slug}
            href={`/blog/${post.slug}`}
            className="card p-6 block hover:shadow-md hover:-translate-y-0.5 transition-all duration-200 group"
          >
            <div className="flex items-center gap-3 mb-3">
              <span className="text-xs text-surface-400 dark:text-surface-500 font-mono">
                {formatDate(post.date)}
              </span>
              <div className="flex gap-1">
                {post.tags.map((t) => (
                  <span
                    key={t}
                    className="text-xs font-medium px-2 py-0.5 rounded-full bg-brand-50 dark:bg-brand-900/20 text-brand-600 dark:text-brand-400"
                  >
                    {t}
                  </span>
                ))}
              </div>
            </div>
            <h2 className="text-lg font-semibold text-surface-900 dark:text-surface-50 group-hover:text-brand-600 dark:group-hover:text-brand-400 transition-colors mb-2">
              {post.title}
            </h2>
            <p className="text-sm text-surface-600 dark:text-surface-400 leading-relaxed">
              {post.excerpt}
            </p>
            <span className="inline-flex items-center gap-1 mt-3 text-sm text-brand-600 dark:text-brand-400 font-medium">
              Read more
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
              </svg>
            </span>
          </Link>
        ))}
      </div>

    </main>
  );
}
