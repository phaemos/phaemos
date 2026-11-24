import { siteAbsolute } from '@/lib/links';
import { REPO_URL } from '@/lib/site';
import { DOCS_SITE } from '@/components/content/legal';

// a plain-text map of the public site for language model tools (llmstxt.org). It names only pages that exist and says
// only what those pages say. Built once at build time like the sitemap.
export const dynamic = 'force-static';

export function GET(): Response {
  const page = (path: string, name: string, line: string) => `- [${name}](${siteAbsolute(path)}): ${line}`;
  const body = [
    '# PHAEMOS',
    '',
    '> An open industrial IoT platform for predictive maintenance. Sensor nodes send readings to a backend that scores each one against a model of normal behaviour. A live dashboard raises an alert when a machine drifts. The software runs end to end on simulated readings because the sensor nodes are not yet wired to machines. Open source under AGPL-3.0; hardware designs under CERN-OHL-S v2.',
    '',
    '## The project',
    '',
    page('/about', 'About', 'what PHAEMOS is, how a reading travels and what works today'),
    page('/faq', 'FAQ', 'running it, adding machines, alerts, the anomaly model, accounts, hosting and the licence'),
    page('/changelog', 'Changelog', 'every release with its date and notes'),
    page('/blog', 'Blog', 'notes on the model, the firmware and the hardware'),
    page('/status', 'Status', 'whether the API, database and cache answer now'),
    '',
    '## Using it',
    '',
    page('/docs', 'Documentation', 'an index of the setup, architecture, API, sensor and security documents'),
    `- Documentation site (not open yet, planned at ${DOCS_SITE}): the full documents`,
    `- [Source code](${REPO_URL}): the monorepo with the backend, dashboard, firmware, hardware, edge gateway and clients`,
    page('/support', 'Support', 'where to ask and the common setup problems'),
    page('/contact', 'Contact', 'questions and feedback'),
    '',
    '## Policies',
    '',
    page('/privacy', 'Privacy notice', 'what personal data is collected and why'),
    page('/cookies', 'Cookies', 'every cookie and browser storage key'),
    page('/terms', 'Terms', 'the terms for the website and the hosted service'),
    page('/security', 'Security', 'how to report a vulnerability'),
    page('/accessibility', 'Accessibility', 'how accessible the site is and how to report a problem'),
    '',
  ].join('\n');
  return new Response(body, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
}
