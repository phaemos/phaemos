---
title: "Accessibility statement"
description: "What is built in for accessibility on the PHAEMOS website and dashboard, what has been checked and what has not."
version: "[PUBLICATION DATE]"
versionLabel: "Prepared on"
---

This statement covers the PHAEMOS website at {site} and the dashboard at {app}.

PHAEMOS is used by people who look after machines, often on a workshop floor, on a phone or with gloves on. We want it to work with a keyboard, without relying on colour and for people who do not see the screen well or at all.

## The standard we aim for

We aim to meet the Web Content Accessibility Guidelines (WCAG) 2.2 at level AA.

## Where we are today

We have not yet had the website or the dashboard fully evaluated against WCAG 2.2, so we do not claim that they conform. This section says what has been built, what has been checked and what has not.

### What is built in

- Every page declares its language and puts its content inside one main landmark.
- A "Skip to content" link comes before the navigation on the website and on the dashboard.
- One focus style applies everywhere: a 2 pixel outline that page styles cannot switch off.
- Buttons, text fields and menus are at least 44 pixels high. Compact buttons keep a 44 pixel area that responds to a press.
- Controls are native buttons, links and form fields, reached in the order they appear.
- Animation and transitions are turned off when your device asks for reduced motion.
- Light and dark themes are both supported. The choice is yours and is remembered.
- Status is never shown by colour alone. Badges carry a word and a shape as well.
- Each chart has a title, a one-sentence description and the same numbers in a table that screen readers can read.
- Tables have captions and marked header cells.
- Error messages and results of actions are announced to screen readers when they appear.
- Confirmation dialogs use the browser's own dialog element, which keeps focus inside until the dialog closes.
- The cookie banner is a labelled dialog that comes first in the page order. It does not cover the page and it takes focus when you open it from Cookie settings. {if analytics}
- Alerts can also reach people by email{if brevo: and critical alerts by text message to the owner of the machine}, so nobody has to be watching the screen. The email goes to a list that the people who run the service choose.

### What has been checked and how

We assessed the site ourselves. Nobody outside the project has audited it.

- Colour contrast was calculated from the colour values for the dashboard's text, chart lines, status bars, borders and links in both themes. All 28 pairs we checked meet the level AA ratios: 4.5 to 1 for text and 3 to 1 for graphics and borders.
- The size of interactive controls was measured by a script on the dashboard pages at desktop width and at phone width.
- The points under "What is built in" were checked by reading the code and by using the pages.

### What has not been tested

- No testing with a screen reader such as VoiceOver, NVDA, JAWS or TalkBack.
- No testing with voice control or switch access.
- No structured check of every WCAG 2.2 success criterion.
- No check at 200% and 400% zoom on every page.
- No testing by disabled users.

## Known limitations

- **Charts.** The charts are drawn for sighted reading. The table behind each chart holds a sample of the points when there are many. The last 24 hours of readings can be exported as a CSV file from a machine's page.
- **Live readings.** The dashboard refreshes a machine's readings every few seconds while its page is open and shows a reading pushed over the live connection within a couple of seconds. When the live connection stops the page says so and keeps refreshing on its own. We have not checked how often a screen reader announces those updates.
- **Contact form check.** The contact form uses a check from Cloudflare that we do not control. If it stops you sending the form, email [contact@phaemos.com](mailto:contact@phaemos.com).
- **Documentation site.** docs.phaemos.com is built with a separate theme that we have not assessed. {if hosted}
- **Status page.** status.phaemos.com is hosted by Instatus and is outside our control. The status page at {site}/status says in plain text whether the API is answering. {if hosted}
- **Sensor nodes.** A node's LEDs show its state by light. The same state is shown in words on the dashboard.

## What it is built with

The website and the dashboard rely on HTML, CSS, JavaScript and WAI-ARIA. The dashboard needs JavaScript turned on. The public pages show their content without it. We build for current versions of the common browsers and have not tested older ones.

## If something does not work for you

Tell us. We treat accessibility problems as bugs.

- Open an [issue on GitHub](https://github.com/phaemos/phaemos/issues/new/choose) with the `accessibility` label.
- If you would rather not use GitHub, email [support@phaemos.com](mailto:support@phaemos.com).

Say what you were trying to do, what happened and what would have worked better. Mention the device, browser and any assistive technology you use if you think it matters.

If you need something from the site in another form, such as the readings behind a chart or the text of a page by email, ask at the same address and we will send it.

## How this statement was prepared

This statement was prepared on [PUBLICATION DATE] from a self-assessment by the people who build PHAEMOS. We will review it when the site changes in a way that affects accessibility and at least once a year.
