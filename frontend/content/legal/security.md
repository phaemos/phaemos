---
title: "Security"
description: "How to report a security problem in PHAEMOS, what happens when you do and which security controls are in place today."
version: "[PUBLICATION DATE]"
versionLabel: "Version date"
---

How to report a security problem in PHAEMOS, what happens when you do and which security controls are in place today.

## Reporting a vulnerability

Report it privately. Do not open a public issue or discussion.

1. Use [GitHub Security Advisories](https://github.com/phaemos/phaemos/security/advisories/new). This is the route we prefer because the report stays private and we can work on the fix with you there.
2. If you cannot use that, email [security@phaemos.com](mailto:security@phaemos.com).

Email is not encrypted. If your report includes something sensitive, such as a working exploit or data you came across, say so in a first short message and we will agree a safer way to send it.

## What to include

- Where the problem is: the address, the API route, the file or the component.
- What kind of problem it is, for example cross-site scripting or a missing access check.
- Steps to reproduce it. A harmless proof of concept is best.
- What an attacker could do with it.
- The version or commit you tested.
- Whether you tested our hosted service or your own copy.
- A fix, if you have one in mind.
- The name or handle to credit. Say so if you would rather not be named.

You can report without giving your name. We can only reply if you give us a way to reach you.

## What to expect from us

- We reply within 72 hours to confirm we have your report.
- We tell you whether we can reproduce it and how serious we think it is.
- We keep you informed while we work on a fix and tell you when it is released. You are welcome to check that the fix works.
- If we decide a report is not a vulnerability or is out of scope, we tell you why.
- We do not ask you to sign a non-disclosure agreement.

We decide the order of fixes by impact, severity and how easy the problem is to exploit.

## Scope

In scope:

- The code in the [phaemos/phaemos](https://github.com/phaemos/phaemos) repository: the backend API, the dashboard and website and the firmware. Only the latest commit on `main` is maintained.
- The website we run: {site}{if split:, {app}}{if hosted:, {api} and docs.phaemos.com}.

Out of scope:

- status.phaemos.com, which Instatus hosts. Report problems there to Instatus. {if hosted}
- The platforms we run on and the services we call, such as our hosting, email{if brevo:, text message} and bot check providers. Report problems in those to the provider. Do tell us if we have set one of them up insecurely.
- Third-party libraries. Report those to their maintainers. Do tell us if the way we use a library makes it exploitable.
- A copy of PHAEMOS that someone else runs. A flaw in the code is in scope and comes to us. Testing their installation needs their permission, not ours.

## Rules for testing

The safest way to test is on your own copy. PHAEMOS is open source and runs locally with one command, so you can try anything there without touching anyone's data.

{if hosted:If you test the hosted service}{if not hosted:If you test a copy of PHAEMOS}, you must:

- use only an account you have been given. Accounts are by invitation, so ask us at [security@phaemos.com](mailto:security@phaemos.com) if you need a test account {if hosted}
- use only a copy that you run yourself or that its owner has given you permission to test. The hosted service is not open yet {if not hosted}
- stop as soon as you have shown that the problem exists
- stop and tell us straight away if you come across personal data or another person's content. Do not copy it, keep it or share it
- delete anything you retrieved within one month of the problem being fixed
- keep the details private until we have agreed a disclosure date with you.

You must not:

- break the law
- read, change or delete data that is not yours beyond the minimum needed to show the problem
- run denial of service tests or send traffic in volumes that could slow the service for others
- use automated scanners at a rate that the rate limits would not allow a normal user
- use phishing or any other social engineering against our people or users
- attack our people, our devices or any physical site
- test the systems of our providers
- ask for payment in return for a report.

## Safe harbour

If you act in good faith and follow this policy:

- we treat your testing of the systems we control as authorised by us
- we will not take legal action against you over it
- we will not ask the police to investigate you over it
- if someone else takes action against you for research that followed this policy, we will make it known that you acted within it.

This covers only the systems we control. We cannot give permission on behalf of our providers or anyone else. This policy does not allow anything that is against the law. If you are unsure whether something is within the policy, ask us before you do it.

## Reports we do not treat as vulnerabilities

- Missing headers or settings that are only "best practice", with no way shown to exploit them.
- TLS configuration findings with no practical attack.
- Output from an automated scanner that has not been checked by hand.
- Denial of service by volume.
- Spam or social engineering.
- Problems that need a victim's unlocked device or a browser that is years out of date.
- Anything under "Known limits" below, unless you have found a way to exploit it that we have not described.

## Rewards

We do not pay bounties or other rewards. We do thank people publicly.

## Coordinated disclosure

We publish a security advisory on GitHub together with the release that fixes the problem. Please give us reasonable time to release a fix before you publish anything. We ask for 90 days from your report unless we agree something different with you. If a problem is already being exploited we will move faster and will agree an earlier date.

## Credit

With your permission we name you in the advisory and in the release notes. Tell us the name or handle you want us to use. If you would rather stay anonymous, we leave your name out.

## Controls in place

What the code and the server set-up enforce today. The fuller record is in the [security document](https://github.com/phaemos/phaemos/tree/main/docs/security.md).

| Control | What it does |
| --- | --- |
| Accounts by invitation | Public registration is closed. That covers the registration route{if google|github|microsoft: and a first sign-in through {providers}}. An admin invites each person with a link that lasts 48 hours. The first admin is made by a command run on the server. |
| Passwords | Stored as bcrypt hashes. A password needs at least 8 characters with one capital letter and one digit. It can be at most 72 bytes. |
| Sign-in lockout | An account is never locked for good by wrong guesses, because that would let anyone who knew an address keep its owner out. Failures are counted for each account and place: after five wrong passwords or codes from one place that place waits 30 seconds, then 60, 120 and so on up to 15 minutes and is answered 429 with a Retry-After header. An unknown address is counted and answered exactly like a known one. Across all places, a browser that has not signed in to the account before may try once every 10 seconds while the account is being guessed at and the owner is emailed. Admin accounts rely on the per-place wait, two-step sign-in and the per-address rate limit. The same count applies on every route that asks for a proof. A wrong proof is answered with 400. |
| Two-step sign-in | An optional authenticator app code. Once it is on it is asked for at every sign-in, including sign-in through a provider. A correct password alone returns a challenge that expires after 5 minutes and works only at the code step. A code is accepted once. |
| Sign-in with a provider | {providers_and}. A cookie that lasts 10 minutes ties the return from the provider to the browser that started the sign-in. Google and GitHub sign-ins are accepted only with an email address the provider has verified. A Microsoft address is never used to link to an existing account. No token is placed in a web address. {if google|github:A password account can link {linkable} from its profile page after proving it is the owner and only when the provider's verified address is the account's own address.} | {if google|github|microsoft}
| Session tokens | The access token lasts 15 minutes. The refresh token lasts up to 7 days and never longer than the session it belongs to, which ends 30 days after sign-in. It is in an httpOnly cookie that is marked Secure outside local development and is sent only to the two routes that read it, the one that renews a session and the one that ends it. Each sign-in is a session that the server keeps. A refresh token works once and is swapped for a new one at each renewal. Using an old one a second time ends the session. Signing out ends the session at once. Each token states its type, so one kind cannot stand in for another. Changing a password or two-step settings ends every other session. |
| Roles | Admin, technician and viewer. An unknown or empty role gets nothing. Viewers are read-only. Creating or deleting a machine, alert rules, webhooks, maintenance windows, firmware uploads, model retraining, invitations, the user list and the audit log are for admins. |
| Machine access rule | One rule decides who may see and who may change a machine. Admins and viewers see every machine. A technician sees only their own machines and machines nobody owns. Admins change every machine, technicians their own and unowned ones, viewers none. The rule applies to machines, readings, the readings export, anomaly history, alerts, alert rules, tickets, maintenance windows, the health totals and the live readings connection. A machine you may not see answers exactly like one that does not exist. |
| Tickets and alerts | Resolving an alert and creating or editing a ticket need an admin or a technician with write access to that machine. A ticket that names an alert must use an alert that belongs to the machine named. |
| Live readings | The live connection for a machine opens with no token in its address. The access token goes in the first message, which must arrive within 5 seconds and be at most 4096 characters. The connection is accepted only for a valid access token from a session that has not ended, held by someone the machine access rule allows. One account may hold 5 connections. A refused client is closed at once with code 1008 and is sent nothing. An open connection closes when its token expires and is checked again every 60 seconds. |
| Node API keys | Each machine has its own random key. A node sends it in the `X-API-Key` header to post readings. Only a keyed hash of the key is stored, so a key is shown once, when the machine is made or the key is replaced and no route returns it again. An admin or the machine's owner can replace it, after proving it is them again with their password or a two-step code. The old one stops working at once. |
| Replay protection | A node that sends a boot count and a sequence number is protected from then on: a post that is not newer than the last one accepted is refused or answered as a duplicate and a sudden jump in the counters is recorded as a warning that the key may be known to someone else. |
| API tokens | A script or the command line tool can use an API token instead of a password. It has a scope (read, operate or admin) and an expiry of at most a year. Only a keyed hash of the secret is stored and the secret is shown once. A token can never change a password, two-step sign-in, an email address or a session and changing a password or two-step sign-in revokes every token. A service account, which cannot sign in, can own API tokens for an integration. |
| Webhooks | Adding or changing one or making a new signing secret, needs an admin to prove it is them again. The address must be `https` and every address its host resolves to must be public, so a private, loopback or link-local address is refused. It is checked again at each delivery and a redirect is never followed. A webhook in the signed JSON format has its own secret. Each delivery carries an `X-Phaemos-Signature` header with a timestamp and an HMAC-SHA256 of the timestamp and the exact body, so the receiver can check who sent it and refuse a replay older than five minutes. The secret is encrypted on the server, shown once and never returned again. A chat message template is checked when it is saved and can use only five named placeholders. A create that is sent twice with the same `Idempotency-Key` makes one webhook. |
| Firmware | Uploads are for admins. Only `.bin` files up to 2 MB are accepted and a SHA-256 checksum is recorded. Checking for firmware and downloading it both need the key of a registered machine. |
| Rate limits | Counted for each IP address. Sign-in 5 a minute. Registration and invitations 10 an hour. Account deletion 5 an hour. Password change, two-step codes and accepting an invitation 10 a minute. Contact form 3 messages an hour. Firmware uploads 20 an hour, firmware checks 30 a minute and downloads 10 a minute. Reading history and exports 600 a minute. Webhook tests 10 a minute. Readings posted by a machine are refused above 60 a minute. A request that is refused for going over a limit is answered 429 with a `Retry-After` header and a sentence that says how many seconds to wait. The dashboard counts the wait down. The address is taken from the proxy header only when the request really came from our own proxy. |
| Limits on bulk reads | One history request returns at most 5,000 readings. One export covers at most 31 days. |
| Error replies | Every error from the API has one shape: a fixed `code` that a program can act on, a `detail` sentence for a person and a `request_id` that is also sent in the `X-Request-ID` header. The dashboard shows the reference in small text beside a failed action, so a person can quote it when they ask for help. The same reference is in the server log. A reply to a request that fails validation says where the fault is and what kind it is. It does not repeat what was sent, so a mistyped password is never echoed back. |
| Browser access to the API | Cross-origin requests are allowed only from the configured dashboard addresses, with a fixed list of methods and headers. |
| Response headers on the website and dashboard | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, a `strict-origin-when-cross-origin` referrer policy and a permissions policy that turns off the camera, microphone and location. `Strict-Transport-Security` for two years with subdomains. An enforced Content-Security-Policy that limits sources to the site and the API. It adds Cloudflare Turnstile{if analytics: and Google Analytics} only when they are configured. It forbids framing and plugins. The production policy does not allow script evaluation. {if split:Pages that hold the access token (the dashboard, sign-in and invitation pages) allow no inline script and load no third-party script.}{if not split:This installation serves the site and the dashboard from one address, so the public pages share the browser storage of the dashboard and still allow inline script.} `Cross-Origin-Opener-Policy` and `Cross-Origin-Resource-Policy` are `same-origin`. |
| Contact form | The Turnstile check is verified on the server. Outside development the form refuses messages when the check is not configured. Text from visitors is stripped of control characters, capped in length and escaped before it goes into an email. |
| Audit log | Records ticket creation and edits, resolved alerts, key replacements, machine deletions, firmware uploads, model retraining, the nightly clean-up of old readings and the times when alert emails or texts are paused by the daily limit, with who did it and when. An admin can export it. The export is signed with HMAC-SHA256 so a copy can be checked. |
| Logs | The API does not write an access log of each request. Its own log removes query strings from connection lines. The proxy leaves the live readings connection out of its access log. No token travels in a web address. When an email{if brevo: or text} fails to send, the log holds an error code and never the address, the number or the message. |
| API documentation | The interactive API pages and the schema are switched off outside development. |
| Signing key | The API refuses to start without a signing key. Outside development it also refuses a key that is short or looks like a placeholder. |
| Network | The database and the cache are not reachable from the internet. The API listens only on the server itself, behind a proxy that answers for the API's own name alone. The request metrics route is blocked at the proxy. |
| Container | The API runs as an unprivileged user inside its container and the production image holds no test software. |
| Server | Sign-in to the server is by SSH key only and not as root. A firewall allows SSH and web traffic only. Repeated failed SSH sign-ins are banned for an hour. Security updates install automatically. |
| Data retention | A nightly job deletes readings recorded more than 90 days earlier, closed tickets 24 months after their last update, resolved alerts 12 months after they were resolved and log entries after 12 months. Sign-in session records are deleted a day after they expire. |
| Your data | Anyone signed in can download their profile data as JSON and delete their account from the profile page, which asks for their password first and for a current two-step code as well when that is on. An account that signs in through a provider uses a two-step code or a provider sign-in in the last 5 minutes instead. |

## Known limits

- The dashboard keeps your access token in localStorage, where script on the dashboard can read it. The cookie the page guard reads holds only a marker and no token. The refresh token is httpOnly.
- The public website's Content-Security-Policy still allows inline scripts, which its static pages need. The dashboard, sign-in and invitation pages allow none: a script runs there only if it carries a number made for that one request.
- Signing out ends your session on the server and removes the session cookies from your browser. Sessions in other browsers stay signed in until they expire, until you end them from your profile page or until you change your password, your two-step settings or your sign-in email address. The record of the session stays on the server until it expires.
- A new email address is not confirmed with a link before it is used. Changing it needs the password (and a two-step code when that is on), can be done up to 3 times an hour and 5 times a day, ends the other sessions and sends a notice to the old address unless that address was typed in less than an hour ago and never confirmed. Changing the phone number that receives critical alert texts needs the same proof.
- Two-step secrets are stored in the database as they are, not hashed or separately encrypted.
- Database backups are kept on the same server and are not encrypted.
- Rate limit counts are held in memory and start again when the API restarts.
- The audit log does not yet record changes to accounts, roles, invitations, webhooks, alert rules or maintenance windows.
- Backup codes for the authenticator app are not built. Sign in with Apple is not built either.
- There is no password reset by email. A signed-in user can change their password from the profile page.

## security.txt

A machine-readable copy of the contact details is published at [/.well-known/security.txt](/.well-known/security.txt) as described in RFC 9116.
