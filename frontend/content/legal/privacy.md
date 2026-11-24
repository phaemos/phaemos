---
title: "Privacy notice"
description: "What personal data PHAEMOS collects, why we use it, who receives it, how long we keep it and what you can do about it."
version: "[PUBLICATION DATE]"
versionLabel: "Version date"
---

This notice explains what personal data the PHAEMOS website{if hosted: and hosted service} collect, why we use it, who receives it, how long we keep it and what you can do about it.

## 1. Who we are

PHAEMOS is run by Isaac Adjei as an individual. There is no company behind it. In this notice "we" means Isaac Adjei. We are the controller of the personal data described here, which means we decide why and how it is used.

You can reach us about anything in this notice:

- By email: [privacy@phaemos.com](mailto:privacy@phaemos.com)
- By post: [POSTAL ADDRESS OF THE CONTROLLER] {if hosted}

:::if not hosted
We do not publish a postal address while the hosted service is not open to accounts. Email reaches us about everything in this notice.

:::

We have not appointed a data protection officer because the law does not require us to have one.

:::if hosted
We are registered with the Information Commissioner's Office (ICO) under number [ICO REGISTRATION NUMBER].
:::
:::if not hosted
We will publish our registration with the Information Commissioner's Office (ICO) here before the hosted service opens to accounts.
:::

## 2. What this notice covers

It covers the services we run ourselves:

- The public website at {site}.
- The dashboard at {app}, for people we have invited. {if hosted}
- The API at {api} that the dashboard and the sensor nodes talk to. {if hosted}
- The documentation site at docs.phaemos.com. {if hosted}
- The status page at status.phaemos.com, which Instatus hosts for us. {if hosted}
- Email you send to a phaemos.com address.

It does not cover a copy of PHAEMOS that someone else runs. Section 15 explains that.

## 3. What we collect, why and on what lawful basis

Data protection law requires a lawful basis for each use of personal data. We name ours in each table.

### When you visit the website

:::if not analytics|pageviews
The website uses no analytics: nothing counts or follows your visits beyond the server logs described below.
:::

| What | Why we use it | Lawful basis |
| --- | --- | --- |
| Your IP address, your browser details and the address of each page you ask for. Vercel, which hosts the site, receives these with every request. | To deliver the pages and keep the site secure. | Legitimate interests: running a working and secure website. |
| Page view counts from Vercel Web Analytics, on the public website only: the page address, the page you came from, the country, region and city worked out from your IP address, your browser, your operating system and your device type. Vercel says it works without third-party cookies and recognises a visitor for no longer than 24 hours through a hash made from the request. | To see which pages are read, in totals only. | Legitimate interests: knowing which pages are used so we can improve them. | {if pageviews}
| Google Analytics data, only if you accept analytics in the cookie banner: page views and how you move through the public website, tied to a random identifier kept in the `_ga` cookies. It does not run on the dashboard or the sign-in pages. | To measure how the site is used. | Consent. You can withdraw it at any time with [Cookie settings](#cookie-settings). | {if analytics}
| Your IP address when the status page at {site}/status asks the API whether it is up. Your browser sends that request every 30 seconds while the page is open. | To show you the current status. | Legitimate interests: showing visitors whether the service is working. |

Your theme choice{if analytics: and your cookie choice} {if analytics:are}{if not analytics:is} saved in your own browser. {if analytics:They are}{if not analytics:It is} not sent to us.

### When you use the contact form

| What | Why we use it | Lawful basis |
| --- | --- | --- |
| The name, email address, subject and message you type. | To read your message and reply to you. | Legitimate interests: answering people who write to us. |
| Your IP address and the result of the Cloudflare Turnstile check. Turnstile also reads technical signals from your browser. | To tell people from bots and limit the form to 3 messages an hour from one address. | Legitimate interests: keeping spam and abuse out of the form. |

The message is sent to our mailbox as an email. The API does not store it.

### When you have an account

Accounts are by invitation. An admin types your email address and picks a role. We email you a link that works for 48 hours. Your account is created when you open the link and choose a name and a password.

| What | Why we use it | Lawful basis |
| --- | --- | --- |
| Your name, your email address and your role (admin, technician or viewer). | To create your account, show you the right machines and let colleagues see who did what. | Contract: we need these to give you the service under our terms. |
| Your password, stored only as a bcrypt hash. We never store the password itself. | To sign you in. | Contract. |
| When your account was created and when you last signed in. | To run and secure accounts. | Legitimate interests: keeping accounts secure. |
| A count of failed sign-in attempts, kept for each account and for the place they came from (not the address itself, only its network). After five wrong passwords or codes from one place that place waits 30 seconds and then longer, up to 15 minutes. An account is never locked for good. | To stop password guessing. | Legitimate interests: keeping accounts secure. |
| If you turn on two-step sign-in: the secret your authenticator app shares with us and the last code step we accepted. | To check your codes and refuse a code that has been used. | Contract: you asked for this feature. |
| A phone number, only if you add one and whether you have confirmed it. {if brevo:To confirm it we text a six digit code to the number, keep a keyed hash of the code for 10 minutes and delete it once the number is confirmed.} | {if brevo:To text you when a critical alert fires on a machine you own. Texts go only to a confirmed number.}{if not brevo:It is stored on your account. No text messages are sent at present.} | Contract: you asked for this feature. |
| The API tokens you make: a name, the scope, when it was made, when it was last used and when it runs out. A keyed hash of the secret, never the secret. | To let a script or the command line tool act as you, with no more than the scope you chose. | Contract: you asked for this feature. |
| Session tokens kept in cookies and in your browser's storage, a session version number on your account and a record of each sign-in session on our server: when it started, when it was last used, when it expires and a coarse description of the browser (such as "Chrome on macOS"), made from its name and not from its full details. For a provider account the record also holds the time of the last provider sign-in. A sign-in lasts at most 30 days, however often it is renewed. | To keep you signed in, to end a session when you sign out and to end every session when you change your password or two-step settings. | Contract. |
| Which machines you own. | To decide what you may see and change. | Contract. |
| Your IP address. | To limit how often sign-in and other requests can be made from one address. | Legitimate interests: protecting the service from abuse. |

Admins can see the list of users: name, email address, role, sign-in provider, whether two-step sign-in is on, whether the account is active, when the person last signed in, how many sessions are open, the account identifier and when the account was created. Admins do not see phone numbers. Admins can change a role, deactivate or remove an account, clear two-step sign-in and send a reset link to the person's own address and each of those is recorded in the log of changes.

:::if google|github|microsoft
### When you sign in through {providers}

This is optional. If you choose it, the provider tells us who you are.

| What | Why we use it | Lawful basis |
| --- | --- | --- |
| From Google: your name, your email address, whether Google has verified that address and Google's identifier for you. | To sign you in without a password. | Contract: you chose this way to sign in. | {if google}
| From GitHub: your name or username, your verified email addresses and GitHub's identifier for you. We use one verified address and do not store the others. | The same. | Contract. | {if github}
| From Microsoft: your display name, your email address or sign-in name and Microsoft's identifier for you. | The same. | Contract. | {if microsoft}

{if google|github:A password account can also link {linkable} from its profile page and the same data is then stored. }We store the provider's name and its identifier for you on your account. We do not store the access token the provider gives us. The provider learns that you signed in to PHAEMOS and handles that under its own privacy notice.
:::

### When PHAEMOS sends alerts

| What | Why we use it | Lawful basis |
| --- | --- | --- |
| The email addresses on our alert list. We choose these addresses ourselves. They belong to people who run the service. | To email a warning or critical alert. | Legitimate interests: telling the people responsible that a machine needs attention. |
| Your phone number, if you own a machine and have added a number. | To text you a critical alert about that machine. A text for the same machine, reading and severity is sent no more than once an hour. A text that fails to send does not use up that hour, but the next try waits at least 60 seconds. | Contract: you asked for this feature. | {if brevo}

An alert email{if brevo: or text} names the machine and gives the reading or the anomaly score. It does not name a person.

### When you appear in a ticket or in the log of changes

| What | Why we use it | Lawful basis |
| --- | --- | --- |
| On a ticket: who raised it, who it is assigned to and anything written in its title or description. | To track maintenance work. | Legitimate interests: keeping a record of the work done on each machine. |
| In the log of changes: your account identifier, what you did, when you did it and a short detail such as a ticket title or a machine name. The log covers tickets raised and edited, alerts resolved, machine keys replaced, machines deleted, firmware uploads and model retraining. It also records the nightly clean-up, the creation of the first admin and the times when alert emails or texts are paused because the daily limit was reached, which names that admin's account identifier. | To be able to check who changed what. | Legitimate interests: accountability and security. |

Anyone who may see a ticket can see who raised it and who it is assigned to. Admins can read and export the log of changes. Each person also gets their own entries in the download from their profile page.

Please do not put personal details about other people in ticket text.

### When you report a vulnerability

| What | Why we use it | Lawful basis |
| --- | --- | --- |
| Your name or handle, your contact details and what you tell us in the report. | To investigate the problem, keep you informed and credit you if you want that. | Legitimate interests: fixing security problems and thanking the people who report them. |

Reports made through GitHub Security Advisories are held by GitHub. Reports sent by email are held in our mailbox.

### When you email us or take part on GitHub

If you email a phaemos.com address we keep your message and our reply in our mailbox so we can deal with it. Our lawful basis is legitimate interests: answering people who write to us.

The project's issues, discussions and security advisories are on GitHub. What you post there is handled by GitHub under its own privacy statement and is public unless it is a private advisory.

### Logs and backups

| What | Why we use it | Lawful basis |
| --- | --- | --- |
| The web server in front of the API keeps an access log: IP address, time, the address requested, the response code and your browser details. The live readings connection is left out of this log. | To find faults and investigate abuse. | Legitimate interests: keeping the service working and secure. |
| The API keeps a log of its own: start-up messages, warnings and errors. It also holds a line for each live readings connection with its address and no query string. It does not record each request. An error line can hold an account or machine identifier. When an email{if brevo: or text} fails to send it holds an error code and never the address, the number or the message. | To find and fix faults. | Legitimate interests: keeping the service working. |
| A daily backup of the whole database. | To recover the service after a failure. | Legitimate interests: being able to restore the service. |

### To meet legal duties

We use the data we hold where the law requires it, for example to answer a request to use your rights or a complaint. Our lawful basis is legal obligation.

We do not collect special category data such as health information. We do not sell personal data and we do not use it for advertising.

## 4. Data we get from someone other than you

- Your email address and role, from the admin who invited you.
- Your name, email address and identifier, from {providers} when you sign in through them. {if google|github|microsoft}
- Your name on a ticket, from a colleague who assigns the ticket to you or mentions you in it.

## 5. Whether you have to give us your data

You need to give a name, an email address and a password{if google|github|microsoft: (or a provider sign-in)} to have an account. Without them we cannot create one. A phone number is optional. You can use the public website without giving us anything beyond what your browser sends.

## 6. Who receives your data

We use the services below. Processors act only on our instructions. Controllers decide for themselves how they use what they receive.

| Service | Role | What it receives | Where it processes it |
| --- | --- | --- | --- |
| DigitalOcean | Processor. Hosts the API, its database and the backups on one virtual server. | Everything in sections 3 and 4 that the API stores: accounts, machines, readings, alerts, tickets, the log of changes and the access log. | London, United Kingdom. DigitalOcean is a United States company. | {if hosted}
| Vercel | Processor. Hosts the website at {site}{if split:, the dashboard pages at {app}} and the documentation site. {if pageviews:Provides Vercel Web Analytics.} | Every page request (IP address, browser details, page address) and the page view data in section 3. | Mainly the United States, with servers around the world that deliver pages. |
| Resend | Processor. Sends our email. | Contact form messages (your name, email address, subject and message), invitation emails (the address invited and the role) and alert emails. | United States. | {if hosted}
| Brevo | Processor. Sends our text messages. | The phone number you added and the alert text. | See section 7. | {if brevo}
| Cloudflare (Turnstile) | Processor for the bot check on the contact form. Controller when it uses the same signals to improve its bot detection. | Your IP address, your browser's user agent, a TLS fingerprint and our site key. | United States and the European Economic Area. | {if hosted}
| Google (Analytics) | Processor. Only if you accept analytics. | Page views and the `_ga` identifiers. Google says Google Analytics does not log or store IP addresses. | Google's data centres, including in the United States. | {if analytics}
| {providers} (sign-in) | Controller. Only if you choose that sign-in. | The fact that you are signing in to PHAEMOS. | As set out in each provider's privacy notice. | {if google|github|microsoft}
| Instatus | Processor. Hosts status.phaemos.com. | Your request when you visit that page{if statuspage: and your email address if you subscribe to updates there}. | Mainly the United States. | {if hosted}
| GitHub | Controller. Hosts the project's code, issues, discussions and private security advisories. | What you post there. | As set out in GitHub's privacy statement. |
| Google (Workspace) | Processor. Hosts the phaemos.com mailboxes. | Email you send us and contact form messages. | Data centres that can be outside the United Kingdom. See section 7. |
| The service an admin points a webhook at{if discord: (for example Discord)} | Controller of its own platform. | Alert messages posted through a webhook: the machine name, the reading, its threshold and the severity. No names, email addresses or phone numbers. An admin can choose any public https address, so the service can be one that we do not name here. | As set out in that service's privacy notice. |

We also share personal data when the law requires us to, for example with a court or a regulator.

## 7. Transfers outside the United Kingdom

Several of these services process data in the United States. Two safeguards in UK law matter here.

- The UK-US data bridge. It covers a United States company that has an active listing on the Data Privacy Framework list and has signed up to the UK Extension. {transferrers} each say in their published privacy terms that they have done so.{if hosted: Resend refers to the same framework in its data processing agreement.}
- Approved contract terms for transfers from the United Kingdom. These are the standard contractual clauses with the UK Addendum and the UK international data transfer agreement. The data processing terms of {if hosted:Resend, Vercel, DigitalOcean and Instatus}{if not hosted:Vercel} include them. They apply where the data bridge does not.

{if hosted:The database itself is stored in London, United Kingdom.}

Google Workspace, which holds our mailboxes and the project domain as an alias: the transfer outside the United Kingdom relies on Google Workspace's standard data processing terms, the Cloud Data Processing Addendum. It covers data that is subject to the UK GDPR and where data goes to a country that is not recognised as adequate it provides for transfers under the transfer solution the provider has adopted or standard contractual clauses.

<!-- for the lawyer to confirm: the Cloud Data Processing Addendum (cloud.google.com/terms/data-processing-addendum) names UK GDPR and the UK as an adequate country but its listed standard contractual clauses are the EU ones, so check that a UK transfer mechanism applies to Workspace -->

Brevo: [BREVO PROCESSING LOCATION AND SAFEGUARD] {if brevo}

You can ask us for a copy of the safeguard that applies to a transfer of your data. Write to the address in section 1.

## 8. How long we keep it

| Data | How long |
| --- | --- |
| Your account | Until you delete it from your profile page or ask us to. Deleting from the profile page asks for your password and for a current two-step code as well if you use two-step sign-in{if google|github|microsoft: (an account that signs in through a provider uses a code or a sign-in with the provider in the last 5 minutes instead)}. It is refused while you own machines or are the last admin. We also delete an account that we close under our terms. |
| An invitation that is not accepted | The link stops working after 48 hours. The record of the invitation stays in our database for 30 days after that and is then deleted. {if hosted:Resend keeps its own record of the email it sent.} |
| An invitation that has been used | We keep a hash of the link for about 3 days, so that it cannot be used a second time. The hash is not the link. |
| Sign-in cookies and tokens | Between 5 minutes and 7 days and a sign-in lasts at most 30 days in all. The cookies page lists each one. Signing out removes them from your browser and ends that session on our server. |
| Sign-in session records | The record of a session stays on our server until the session expires, whether or not you signed out. It is deleted a day after that. |
| Tickets and alerts | Closed tickets are deleted 24 months after their last update and resolved alerts 12 months after they were resolved. A resolved alert is kept while a ticket still points at it. Open tickets and unresolved alerts are not deleted by age. When you delete your account your name comes off the tickets you raised or were assigned and the tickets stay until then. |
| The log of changes | Entries are deleted 12 months after they were made. An entry holds your account identifier, not your name. Once your account is deleted that identifier no longer points to you in the live system. |
| Sensor readings | 90 days. A job runs every night at 02:00 UTC and deletes readings recorded more than 90 days earlier. Readings describe machines, not people. |
| Contact form messages and other email | Up to 12 months after our last reply. |
| Vulnerability reports | Until the problem is fixed and disclosed, then for as long as we need the record of the fix. |
| IP addresses used for rate limits | Held in our Redis store for up to one hour. |
| The API web server's access log | 14 days. Older lines are deleted by a daily rotation rule on the server. |
| The API's own log | Kept in files of 10 MB, with three files for each service on the server. When the newest is full the oldest is overwritten, so how long a line lasts depends on how busy the service is. There is no fixed period. |
| Database backups | Seven days on the server. Each night's backup replaces the oldest. Data you delete therefore stays in backups for up to seven days. Copies we keep away from the server are deleted 30 days after they were made. |
| Vercel page view data and request logs | Vercel discards its visitor hash after 24 hours. It keeps request logs for a period set by its own service. |
| Google Analytics data, if you accepted it | The `_ga` cookies last up to 2 years unless you decline later, which removes them. Google Analytics keeps event data for [GOOGLE ANALYTICS RETENTION PERIOD]. | {if analytics}

We review what we hold at least once a year and delete what we no longer need.

## 9. Security

Passwords are stored as bcrypt hashes. Access tokens last 15 minutes. Two-step sign-in is available to every account. The API is reached only over an encrypted connection and the database is not reachable from the internet. The [security page](/security) lists the controls in place and the limits we know about.

No system is perfectly secure. If a breach is likely to put you at high risk we will tell you without undue delay.

## 10. Your rights and how to use them

You have these rights over your personal data. Using them is free.

| Right | What it means | How to use it here |
| --- | --- | --- |
| To be informed | To know how we use your data. | This notice. |
| Of access | To get a copy of your data. | Your profile page has a Download my data button. It gives a JSON file with your profile (including your last sign-in, your sign-in provider and whether two-step sign-in is on), the machines you own, the tickets you raised or were assigned, the maintenance windows you created, your API tokens (their names, scopes and dates, never the secrets) and your own entries in the log of changes. For everything else we hold, write to us. |
| To rectification | To have wrong or incomplete data put right. | Change your name, email address and phone number on your profile page. An account that signs in through a provider cannot change its email address, because the address comes from the provider. You can change your email address up to 3 times an hour and 5 times a day. We email your old address when you change it, unless it was typed in less than an hour ago and never confirmed. Every other session is signed out. We do not confirm the new address with a link first. Changing the phone number that receives critical alert texts needs your password or a current two-step code or a recent provider sign-in, the same as changing your email. Write to us for anything else. |
| To erasure | To have your data deleted. | Your profile page has a Delete my account button. It asks for your password and for a code from your authenticator app as well if two-step sign-in is on{if google|github|microsoft: (an account that signs in through a provider uses a code or a sign-in with the provider in the last 5 minutes instead)}. It then deletes your account. It takes your name off the tickets you raised or were assigned. It is refused while you own machines or are the last admin: an admin hands the machines on or makes another admin first. If that cannot be done write to us. Write to us to have other data deleted, such as an email you sent us or your name in ticket text. |
| To restrict processing | To ask us to hold your data without using it. | Write to us. |
| To object | To object to a use that rests on legitimate interests. We stop unless we have a compelling reason to continue. | Write to us and say which use you object to. |
| To data portability | To receive data you gave us in a form another service can read. | The JSON file from your profile page. |
| To withdraw consent | To change your mind where we rely on consent. | Use [Cookie settings](#cookie-settings) to turn analytics off. It is as easy as turning it on. | {if analytics}
| About automated decisions | Not to be subject to a decision made only by a computer that has a legal or similarly significant effect on you. | We make no such decisions. See section 14. |

What deleting your account leaves behind: the tickets you raised or were assigned, without your name, anything written about you in ticket text, maintenance windows you created (with the creator cleared), entries in the log of changes under an identifier that no longer points to you and backups for the periods in section 8.

To write to us, email [privacy@phaemos.com](mailto:privacy@phaemos.com) or use the postal address in section 1. Say which right you want to use. You can also ask in any other way, including by speaking to us. We may ask for proof that you are who you say you are, usually by replying from the email address on your account.

We reply without undue delay and within one month. If a request is complex we can take up to two more months. The same applies if you have made several requests. We will tell you within the first month if we need that time and why.

## 11. Complaints

If you are unhappy with how we have used your data, tell us first. Email [privacy@phaemos.com](mailto:privacy@phaemos.com) with "Data protection complaint" in the subject. The law asks us to acknowledge a complaint within 30 days of receiving it. We then look into it without undue delay and tell you the outcome.

You also have the right to complain to the regulator at any time:

**Information Commissioner's Office (ICO)**

- Address: 4th Floor, No.3 Circle Square, 5 Hawkshaw Street, Manchester M1 7BL
- Helpline: 0303 123 1113
- Website: [ico.org.uk/make-a-complaint](https://ico.org.uk/make-a-complaint/)

The ICO suggests that you complain to it within three months of our reply.

## 12. Cookies and local storage

We set a small number of cookies and browser storage keys. {if analytics:All but the analytics cookies are }{if not analytics:All of them are }strictly necessary for sign-in, for security or for remembering a choice you made.{if analytics: Google Analytics cookies are set only if you accept them.} The [cookies page](/cookies) lists every cookie and key, who sets it, what it is for and how long it lasts.{if analytics: It also explains how to change your choice.}

## 13. Children

The service is for adults who look after machines at work. You must be 18 or over to have an account. We do not knowingly collect personal data from children. If you believe a child has given us personal data, write to us and we will delete it.

## 14. Automated decisions

PHAEMOS uses a machine learning model to score sensor readings. When a machine's readings stay outside their normal range the model raises an alert and opens a ticket for that machine. The model scores machines. It does not score, rank or profile people.

We do not make decisions about you by automated means alone.

## 15. Self-hosted instances

PHAEMOS is open source and anyone may run their own copy. This notice does not cover those copies. Whoever runs a copy is the controller of the data in it. Ask them for their own privacy notice. We receive no data from a self-hosted copy.

## 16. Changes to this notice

We update this notice when what we do changes. The date at the top shows the latest version. If a change affects how we use data we already hold about you, we will tell account holders by email before it takes effect.
