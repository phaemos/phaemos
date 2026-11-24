import type { ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import SiteHeading from '@/components/ui/SiteHeading';
import Time from '@/components/ui/Time';
import CookieSettingsButton from '@/components/CookieSettingsButton';
import DataTable from '@/components/ui/DataTable';
import TextLink from '@/components/content/TextLink';
import { Code } from '@/components/content/Prose';
import { siteAbsolute } from '@/lib/links';
import { isIsoDay, markPlaceholders, slugify, splitBlocks, type Block, type LegalDoc } from '@/lib/legal';

// no legal sentence lives here. The text comes from a Markdown file in content/legal and this component only lays it
// out: one h1 from the heading, a contents list built from the h2 headings, prose in a column of at most 72 characters (50ch measures about that many characters of this typeface)
// and tables as real tables that scroll inside their own region on a narrow screen.

const LINK = 'text-brand-700 underline underline-offset-2 hover:no-underline dark:text-brand-400';

// the words shown in place of a placeholder, so a draft is never mistaken for a finished page
function Placeholder({ name }: { name?: string }) {
  return (
    <span className="rounded border border-dashed border-warning-700 px-1 font-medium text-surface-900 dark:border-warning-400 dark:text-surface-50">
      to be completed before publication
      {name && <span className="sr-only"> ({name})</span>}
    </span>
  );
}

function textOf(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(textOf).join('');
  if (node && typeof node === 'object' && 'props' in node) return textOf((node as { props: { children?: ReactNode } }).props.children);
  return '';
}

function Link({ href = '', title, children }: { href?: string; title?: string; children?: ReactNode }) {
  if (href === '#placeholder') return <Placeholder name={title} />;
  if (href === '#cookie-settings') return <CookieSettingsButton className="text-brand-700 dark:text-brand-400" />;
  // a plain text file is served by the host and not by a page route
  if (href.endsWith('.txt')) return <a href={href} data-print-href={href.startsWith('/') ? siteAbsolute(href) : undefined} className={LINK}>{children}</a>;
  return <TextLink href={href} printHref={href.startsWith('/') ? siteAbsolute(href) : undefined}>{children}</TextLink>;
}

// one line of Markdown inside a table cell: no paragraph wrapper
function Inline({ text }: { text: string }) {
  return (
    <ReactMarkdown components={{ p: ({ children }) => <>{children}</>, a: ({ href, title, children }) => <Link href={href} title={title}>{children}</Link>, code: ({ children }) => <Code>{children}</Code> }}>
      {markPlaceholders(text)}
    </ReactMarkdown>
  );
}

function LegalTable({ head, rows, caption }: { head: string[]; rows: string[][]; caption: string }) {
  return (
    <DataTable
      caption={caption}
      maxHeightClass="max-h-none"
      minWidth={`${Math.max(head.length * 10, 32)}rem`}
      className="relative max-w-5xl [&_table]:text-base [&_td]:py-3 [&_td]:align-top [&_th]:align-top [&_tbody_th]:py-3"
    >
      <thead>
        <tr>
          {head.map((h, i) => (
            <th key={i} scope="col"><Inline text={h} /></th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, r) => (
          <tr key={r}>
            {row.map((cell, c) =>
              c === 0 ? (
                <th key={c} scope="row"><Inline text={cell} /></th>
              ) : (
                <td key={c}><Inline text={cell} /></td>
              ),
            )}
          </tr>
        ))}
      </tbody>
    </DataTable>
  );
}

// the nearest heading above a table names it for screen readers
function lastHeading(text: string, fallback: string): string {
  const found = [...text.matchAll(/^#{2,3}\s+(.+?)\s*$/gm)].pop();
  return found ? found[1] : fallback;
}

export default function LegalPage({ doc }: { doc: LegalDoc }) {
  // each table is named by the nearest heading above it, worked out before rendering so nothing changes during it
  const blocks = splitBlocks(doc.body).reduce<{ block: Block; caption: string }[]>((acc, block) => {
    const previous = acc.length > 0 ? acc[acc.length - 1].caption : doc.title;
    acc.push({ block, caption: block.kind === 'prose' ? lastHeading(block.text, previous) : previous });
    return acc;
  }, []);

  return (
    <div className="legal-page mx-auto max-w-6xl px-4 py-12 sm:px-6 md:py-16">
      <SiteHeading title={doc.title} />
      <p className="mt-6 text-base text-surface-700 dark:text-surface-300">
        {doc.versionLabel}:{' '}
        {isIsoDay(doc.version) ? <Time value={doc.version} format="date" /> : <Placeholder name="publication date" />}
      </p>

      {doc.toc.length > 0 && (
        <nav aria-labelledby="contents-title" className="mt-8">
          <p id="contents-title" className="text-base font-semibold text-surface-900 dark:text-surface-50">Contents</p>
          <ul className="mt-1 max-w-3xl md:columns-2 md:gap-x-10">
            {doc.toc.map((item) => (
              <li key={item.id} className="break-inside-avoid">
                <a href={`#${item.id}`} className={`inline-flex min-h-[44px] items-center ${LINK}`}>{item.text}</a>
              </li>
            ))}
          </ul>
        </nav>
      )}

      <div className="mt-10 space-y-4 text-base leading-relaxed text-surface-700 dark:text-surface-300">
        {blocks.map(({ block, caption }, i) => {
          if (block.kind === 'table') return <LegalTable key={i} head={block.head} rows={block.rows} caption={caption} />;
          return (
            <div key={i} className="max-w-[50ch] space-y-4">
              <ReactMarkdown
                components={{
                  h1: ({ children }) => <h2 id={slugify(textOf(children))} className="scroll-mt-20 border-t border-surface-200 pt-8 text-2xl font-semibold text-surface-900 dark:border-surface-800 dark:text-surface-50">{children}</h2>,
                  h2: ({ children }) => <h2 id={slugify(textOf(children))} className="mt-6 scroll-mt-20 border-t border-surface-200 pt-8 text-2xl font-semibold tracking-[-0.01em] text-surface-900 dark:border-surface-800 dark:text-surface-50">{children}</h2>,
                  h3: ({ children }) => <h3 id={slugify(textOf(children))} className="mt-4 scroll-mt-20 text-xl font-semibold text-surface-900 dark:text-surface-50">{children}</h3>,
                  ul: ({ children }) => <ul className="list-disc space-y-2 pl-5 marker:text-surface-500">{children}</ul>,
                  ol: ({ children }) => <ol className="list-decimal space-y-2 pl-5 marker:text-surface-500">{children}</ol>,
                  a: ({ href, title, children }) => <Link href={href} title={title}>{children}</Link>,
                  strong: ({ children }) => <strong className="font-semibold text-surface-900 dark:text-surface-50">{children}</strong>,
                  code: ({ children }) => <Code>{children}</Code>,
                }}
              >
                {markPlaceholders(block.text)}
              </ReactMarkdown>
            </div>
          );
        })}
      </div>
    </div>
  );
}
