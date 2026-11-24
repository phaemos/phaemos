// which optional services this installation really uses. The legal pages in this folder are Markdown and a passage
// marked for a service appears only while that service is true here. A notice must never list a service that is not
// switched on, so set each line below to match what is running in production and change it when that changes.
//
// every service is off unless the repository shows it switched on by default. The sample environment files leave every
// key for these services empty, so they all start off.
//
// how a Markdown file uses these keys (the full rules are in lib/legal.ts):
//   :::if brevo            a block, closed by a line holding only :::
//   :::if google|github    a block that shows when any one of the keys is true
//   :::if not analytics    a block that shows when the key is false
//   a table row or list item ending in  {if brevo}
//   a few words inside a sentence:  {if brevo:or text}  and  {if not brevo:instead}

export type ServiceKey = 'hosted' | 'analytics' | 'pageviews' | 'brevo' | 'google' | 'github' | 'microsoft' | 'discord' | 'statuspage' | 'split';

// the two addresses, read the way lib/publicPaths.ts reads them (parseSplitConfig): a valid http or https value for each and
// the two hosts different. This file cannot import that one (the build check runs it under plain Node, which needs file
// extensions that the type checker refuses), so lib/legal.test.mts compares the two on a list of values.
export function hostOf(value: string | undefined): string {
  try {
    const url = new URL((value ?? '').trim());
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return '';
    return url.host.toLowerCase().replace(/\.$/, '');
  } catch {
    return '';
  }
}

export function isSplit(siteUrl: string | undefined, appUrl: string | undefined): boolean {
  const site = hostOf(siteUrl);
  const app = hostOf(appUrl);
  return Boolean(site && app && site !== app);
}

const SPLIT = isSplit(process.env.NEXT_PUBLIC_SITE_URL, process.env.NEXT_PUBLIC_APP_URL);
const apiHost = hostOf(process.env.NEXT_PUBLIC_API_URL);

// the addresses the pages print. With one address the dashboard shares the site's. A local API address is not a published one,
// so the production name stands in for it.
export const LEGAL_VARS = {
  site: hostOf(process.env.NEXT_PUBLIC_SITE_URL) || 'phaemos.com',
  app: SPLIT ? hostOf(process.env.NEXT_PUBLIC_APP_URL) : hostOf(process.env.NEXT_PUBLIC_SITE_URL) || 'phaemos.com',
  api: apiHost && !/^(localhost|127\.|\[)/.test(apiHost) ? apiHost : 'api.phaemos.com',
};

export const SERVICES: Record<ServiceKey, boolean> = {
  // the hosted service is open to accounts. Until it is, the privacy notice and the terms leave out the postal address and the
  // ICO registration number and say the registration will be published first. Set HOSTED_SERVICE_OPEN=1 where the site is built
  // once it opens: the passages that hold those two placeholders then show, so a production build stops until both are filled.
  hosted: process.env.HOSTED_SERVICE_OPEN === '1',

  // the site and the dashboard answer on two addresses. This follows the same two environment values the app uses.
  split: SPLIT,

  // Google Analytics. This follows the same environment value that loads the script and shows the cookie banner, so
  // the notice cannot disagree with the site. Set NEXT_PUBLIC_GA_ID where the dashboard is built and nowhere else.
  analytics: Boolean(process.env.NEXT_PUBLIC_GA_ID),

  // Vercel Web Analytics, the cookieless page view count. It is optional like Google Analytics: it loads only on a Vercel
  // production build with NEXT_PUBLIC_VERCEL_ANALYTICS=1 (app/layout.tsx) and this follows the same value.
  pageviews: process.env.NEXT_PUBLIC_VERCEL_ANALYTICS === '1',

  // text messages for critical alerts, sent through Brevo. Set to true only when BREVO_API_KEY is set on the API.
  brevo: false,

  // sign-in through each provider. Set each to true only when that provider's client id and secret are set on the API.
  google: false,
  github: false,
  microsoft: false,

  // alert messages posted to a Discord channel. Set to true only when DISCORD_WEBHOOK_URL is set on the API.
  discord: false,

  // email subscriptions on the Instatus status page. Set to true only when the status page offers them.
  statuspage: false,
};
