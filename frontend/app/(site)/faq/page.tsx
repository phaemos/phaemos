import type { Metadata } from 'next';
import PageShell from '@/components/content/PageShell';
import Section from '@/components/content/Section';
import TextLink from '@/components/content/TextLink';
import JsonLd from '@/components/content/JsonLd';
import { FAQ_SECTIONS, faqJsonLd } from '@/components/content/faq';
import { DISCUSSIONS_URL } from '@/components/content/legal';

export const metadata: Metadata = {
  title: 'FAQ',
  description: 'Answers about running PHAEMOS, adding machines, alerts, the anomaly model and accounts.',
};

export default function FaqPage() {
  return (
    <PageShell
      title="FAQ"
      lead={
        <>
          Not here? Ask in <TextLink href={DISCUSSIONS_URL}>GitHub Discussions</TextLink>.
        </>
      }
    >
      <JsonLd data={faqJsonLd(FAQ_SECTIONS.flatMap((s) => s.items))} />
      {FAQ_SECTIONS.map(({ id, title, items }) => (
        <Section key={id} id={id} title={title}>
          <div className="space-y-8">
            {items.map(({ q, a }) => (
              <div key={q} className="max-w-[72ch]">
                <h3 className="text-base font-semibold text-surface-900 dark:text-surface-50">{q}</h3>
                <div className="mt-2 space-y-3 text-surface-700 dark:text-surface-300">{a}</div>
              </div>
            ))}
          </div>
        </Section>
      ))}
    </PageShell>
  );
}
