---
title: "Cookies and browser storage"
description: "Every cookie and browser storage key used by the PHAEMOS website, dashboard and API, what it is for and how long it lasts."
version: "[PUBLICATION DATE]"
versionLabel: "Version date"
---

This page lists every cookie and browser storage key used by the public website ({site}){if split: and the dashboard ({app})}{if not split: and the dashboard (which shares that address)} and the API ({api}). Most are strictly necessary: sign-in, security and remembering a choice you made do not work without them, so the law does not require us to ask first. {if analytics:Google Analytics is optional and stays off unless you accept it.}

## Cookies

| Name | Address it belongs to | Set by | What it is for | How long it lasts | Strictly necessary |
| --- | --- | --- | --- | --- | --- |
| `refresh_token` | {api} | The API when you sign in. | Renews your session without asking for your password again. The browser sends `refresh_token` only to two of the API's routes: the one that renews a session and the one that ends it. Scripts on the page cannot read it (httpOnly). | Up to 7 days and never longer than the session it belongs to, which ends 30 days after you sign in. Removed when you sign out, which also ends that session on our server. Each renewal sets a new one. | Yes |
| `kb_` followed by an identifier | {api} | The API when you sign in. | Marks this browser as one that has signed in to your account before. If someone is guessing at your account from many places, this browser is not made to wait while a new one is. It is signed so it cannot be made up and it holds no password or token. httpOnly. | 90 days. | Yes |
| `signin_challenge` | {api} | The API, only when you sign in through {providers} and have two-step sign-in turned on. | Carries the unfinished sign-in from the provider step to the code step. httpOnly. | 5 minutes. | Yes | {if google|github|microsoft}
| `oauth_state` | {api} | The API when you start signing in through {providers}. | Makes sure the return from the provider is accepted only in the browser that started the sign-in. httpOnly. | 10 minutes. | Yes | {if google|github|microsoft}
| `signed_in` | {if split:{app} only}{if not split:{app}} | The dashboard when you sign in. | A marker with the value 1 and nothing else in it, so the dashboard can tell that you are signed in before it shows a page. It holds no token and no credential. | 24 hours. Removed when you sign out. | Yes |
| `_ga` | {site} only | Google Analytics, only after you accept analytics. | Tells one visitor from another with a random identifier. Google Analytics runs on the public website only, never on the dashboard, the sign-in page or the invitation page. Its cookies stay on this one address. | Up to 2 years. Removed if you later decline. | No | {if analytics}
| `_ga_` followed by our measurement ID | {site} only | Google Analytics, only after you accept analytics. | Keeps the state of your current visit. | Up to 2 years. Removed if you later decline. | No | {if analytics}

The public website{if split: at {site}} sets no cookie of its own{if analytics: unless you accept analytics}{if not split: until you sign in, because the dashboard shares its address}.

## Browser storage

These are kept in your browser's localStorage{if google|github|microsoft:, apart from `return_to`, which is in sessionStorage and goes when you close the tab}. They are not sent to us with each request the way cookies are. {if split:A browser keeps a separate store for each address, so a choice saved on {site} is not shared with {app}.}

| Key | Address it belongs to | Set by | What it is for | How long it lasts | Strictly necessary |
| --- | --- | --- | --- | --- | --- |
| `token` | {app} | The dashboard when you sign in. | The dashboard reads your access token from here to call the API. It stops working after 15 minutes and is then replaced. | Until you sign out. | Yes |
| `return_to` | {app} | The dashboard, only when you are asked to sign in with your provider again before deleting your account or turning on two-step sign-in. | Remembers which profile page to bring you back to. | Until you return from your provider or close the tab. | Yes | {if google|github|microsoft}
| `theme` | {if split:{site} and {app}, one for each}{if not split:{site}} | The light and dark switch when you use it. | Remembers the theme you picked so the page does not flash the other one. | Until you clear your browser's site data. | It remembers a display choice you made. You can change it at any time with the same switch. |
| `cookie_consent` | {site} only. The dashboard has no banner and never reads it. | The cookie banner when you make a choice about analytics. | Remembers your choice so we do not ask on every page. | Until you change your choice or clear your browser's site data. | Yes | {if analytics}

:::if not analytics|pageviews
## Analytics

The website uses no analytics of any kind.

:::
:::if pageviews
## Services that run without cookies

Vercel Web Analytics counts page views on the public website only. It does not count the dashboard, the sign-in page or the invitation page. Vercel says it works without third-party cookies and recognises a visitor for no longer than 24 hours through a hash made from the request. The privacy notice says what it records.
:::

## The contact form check

The contact page loads Cloudflare Turnstile, which checks that a person is filling in the form. It runs in a frame served by Cloudflare and reads technical signals from your browser, such as your IP address and browser type. Cloudflare says it collects those signals only to detect and block bots. Turnstile loads on the contact page and nowhere else. Whether Cloudflare's frame sets a cookie or stores anything of its own in your browser has not been checked with a live key. [TURNSTILE COOKIES: CONFIRM BEFORE LAUNCH]

:::if analytics
## How your choice works

- Nothing optional runs until you choose. The Google Analytics script is not loaded unless you press Accept all or allow analytics under Customise.
- Accept all, Reject non-essential and Customise are side by side and look the same. Customise lists the strictly necessary cookies, which are always on and one switch for analytics, which starts off.
- If you reject analytics, Google Analytics stays off. If you had accepted before, we remove the `_ga` cookies and reload the page so the script is gone.
- You can change your mind at any time. Press [Cookie settings](#cookie-settings) in the footer of the website or on the privacy page. The banner opens again with the same three choices.
:::

## Your choices

:::if not analytics
Analytics is not switched on for this site, so there is no banner because there is nothing to choose.

:::
You can block or delete cookies in your browser's settings. If you block the strictly necessary ones you will not be able to sign in.

## Other sites we link to

{if hosted:The documentation at docs.phaemos.com and the status page at status.phaemos.com are separate sites. The status page is hosted by Instatus. This list does not cover them.}{if not hosted:The documentation and the status page are not open yet. They are separate sites and this list will not cover them.}

## More information

The [privacy notice](/privacy) explains what personal data we collect, who receives it and what your rights are. Questions go to [contact@phaemos.com](mailto:contact@phaemos.com).
