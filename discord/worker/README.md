# Commands worker

The small program that answers the slash commands in our Discord server. It runs on the free plan of Cloudflare Workers and holds no bot token. This page takes you from nothing to a working endpoint.

> [!NOTE]
> This folder is published as part of [phaemos/discord](https://github.com/phaemos/discord). Paths here are relative to the `worker` folder.

## What it does

Discord sends every command to one web address as a signed request. The worker checks the signature and answers. Most answers are fixed text from [`../content/commands.toml`](../content/commands.toml). A few read public pages: the latest release and issues from GitHub and the status page of the hosted service. `/report` sends a note to the moderators through one webhook. `/ticket` opens a form and posts it to the staff tickets forum through another. Neither needs a bot token. A ticket's words are never repeated in a message that anyone else can read.

What the worker holds:

| Name | Kind | What it is |
| --- | --- | --- |
| `DISCORD_PUBLIC_KEY` | secret | The application's public key. It is not secret by nature and we keep it out of files all the same |
| `REPORTS_WEBHOOK_URL` | secret | Posts to the moderators' log channel and nowhere else |
| `PROJECT` | variable in `wrangler.toml` | `phaemos`. The worker refuses to run if it does not match the content file |
| `TICKETS_WEBHOOK_URL` | secret | Posts to the staff tickets forum and nowhere else. `/ticket` uses it. `sync-secrets` stores it |
| `TICKET_TAG_IDS` | secret, optional | Pairs such as `kind:id` naming the forum tag for each ticket kind. `sync-secrets` stores it. Without it a ticket still posts, with the kind in its name |
| `STAFF_ROLE_IDS` | secret, recommended | The role ids of Maintainer and Moderator, separated by commas. The staff commands use it to know who is staff |
| `GITHUB_TOKEN` | secret, optional | Read only. Public repositories only. Not needed on day one |

It holds no database, no ids and no member data. The account id is read from your own environment when you deploy and is never written to a file.

## What you need

- Node 24 or later
- A free Cloudflare account
- The Discord application and server from the main README, up to the point where the bot is invited
- The `serverkit` script from the main README, which registers the commands and stores the secrets

## From nothing to a working endpoint

1. **Install the packages.** This runs no package scripts, because `.npmrc` turns them off.

   ```bash
   cd discord/worker
   npm ci
   ```

2. **Run every check.** It builds the content, checks types and style, scans for ids and keys, runs the tests and makes a local bundle. Nothing is sent anywhere.

   ```bash
   npm run verify
   ```

3. **Sign in to Cloudflare.** A browser window opens.

   ```bash
   npx wrangler login
   ```

4. **Set the date.** Open `wrangler.toml` and replace the placeholder after `compatibility_date` with today's date in the form `2026-11-30`. Wrangler refuses to deploy until you do. This is on purpose, so a copy of the file cannot go live by accident.

5. **Choose the account.** If you have more than one Cloudflare account, wrangler asks. In a script you can set `CLOUDFLARE_ACCOUNT_ID` in that terminal session only. Never put it in a file.

6. **Deploy.** The `deploy` script runs every check first.

   ```bash
   npm run deploy
   ```

   Note the address it prints. It ends in `workers.dev`. Until the secrets exist the worker answers every request with an error. That is safe.

7. **Set the two secrets.** Each command asks for the value and hides it, so it never reaches a file or your shell history.

   ```bash
   npx wrangler secret put DISCORD_PUBLIC_KEY
   npx wrangler secret put REPORTS_WEBHOOK_URL
   npx wrangler secret put TICKETS_WEBHOOK_URL
   ```

   Then set the staff roles. In Discord turn on Developer Mode in your own settings (Advanced) and right-click each of the Maintainer and Moderator roles in Server Settings, Roles, to copy its id. Paste them with a comma between them when asked:

   ```bash
   npx wrangler secret put STAFF_ROLE_IDS
   ```

   Without this secret the staff commands fall back to the Manage Messages permission of the request. That permission is worked out for the channel the command is used in and moderators are denied it in the log channel, so `/mod` would refuse them there. Set the secret. A secret that holds no valid id lets nobody in.

   The public key is on the application's General Information page in the [developer portal](https://discord.com/developers/applications). The webhook address is the one for the "Reports" webhook that `serverkit apply` created in the log channel. The quicker way is `python -m serverkit sync-secrets --layout layout/phaemos.toml` from the folder above, which reads both from Discord and stores them without showing them.

8. **Check the address.** Replace `ADDRESS` with the one from step 6.

   ```bash
   curl -s https://ADDRESS/healthz
   curl -i -s -X POST https://ADDRESS/interactions -d '{"type":1}'
   ```

   The first prints `ok`. The second must print `401`. A request without a valid signature is always refused.

9. **Point Discord at the worker.** Either paste `https://ADDRESS/interactions` into "Interactions Endpoint URL" on the General Information page and press Save. The other way is to let the script do it:

   ```bash
   export DISCORD_INTERACTIONS_URL="https://ADDRESS/interactions"
   python -m serverkit apply --layout layout/phaemos.toml
   ```

   This is the PING check. Discord sends a PING and also a request with a deliberately wrong signature. It accepts the address only when the first is answered and the second is refused. If Save fails, the secrets are missing or wrong. Run `npx wrangler tail` in another terminal to watch the attempt.

10. **Register the commands.** The same `serverkit apply` run registers the commands from `../content/commands.toml`. Type `/help` in the server to see them.

11. **Look at the cost.** In the Cloudflare dashboard open the worker and check the request count and the CPU time for a few commands. The free plan allows 100,000 requests a day and 10 ms of CPU time for each request. We designed for about one millisecond.

## What a report sends and who sees it

Every moderator and every Maintainer can read the log channel, so a report names the reporter to all of them. The command, the form and the thank-you all say so before or as they send. They also say that a report about a member of staff goes to the contact address in `../content/commands.toml` and not through Discord.

The entry holds exactly: who reported (a mention that does not ping), who it is about (`/report` only and only when the member option is used), where and the reporter's words.

For the message command we promised the first 500 characters of the reported message. We do not send them. The form's id is handed back by the reporter's own app, so anything carried in it could be altered. The worker keeps nothing between the form opening and the form being sent. So the form id carries only the message id and the entry has a jump link and the words "The link is the evidence". The channel in the link comes from Discord's own signed request. Staff open the link to read the message. A forged message id can point only at another message in the same channel.

## Lookups and the three second rule

`/release`, `/issue show` and `/status` answer in the same request with a time-out of 2.2 seconds on the outside call, then fall back to a plain answer with the link. We do not defer them, because Discord does not let a deferred reply change from public to private. That keeps "number not found" private to the person who asked.

## A flood of junk requests

On the free `workers.dev` address every request counts towards the 100,000 a day, including unsigned junk. A rate-limit rule cannot be attached to that address. A flood can therefore use up the day's requests so that the commands fail until midnight UTC. Nothing else is affected. The rest of the server does not depend on the worker.

A flood cannot cost money. The free plan has no overage bill. Do not move the worker to the paid plan without reading its pricing first. A request without a valid signature is refused before the body is parsed and before any secret is read. It makes no call to GitHub or Discord and touches no data, because the worker has none.

If this ever happens, the later fix is a custom domain on a Cloudflare zone with a rate-limit rule on `/interactions`. That is optional and not needed to start.

## Changing a command

1. Edit `../content/commands.toml`.
2. Run `npm run content` to rebuild `src/content.generated.json`, then `npm run verify`.
3. Run `npm run deploy`.
4. Run `serverkit apply` so Discord learns about a new name or option. A change to wording only needs the deploy.

## What the worker will not do

- Answer a request with a signature that does not verify. The same goes for a timestamp more than five minutes from the worker's own clock. Discord's documentation sets no age limit for the timestamp. The five minutes is our own choice.
- Read a request body over 128 KiB.
- Treat anything in a form id as proof. See the report section above.
- Call anything but the public GitHub API, the status address in the content file and the reports webhook. Each call has a time-out and a size limit. Nothing a member types goes into an address except an issue number, which is a whole number from 1 to 99999999.
- Ping anyone. Every answer carries `allowed_mentions` with nothing allowed.

## When something goes wrong

- **Save fails in the developer portal.** Check the two secrets with `npx wrangler secret list`. The worker answers 500 and logs `misconfigured` when the key is missing or `PROJECT` differs from the content file.
- **Commands say the application did not respond.** The worker may be over its daily request count. The rest of the server does not depend on it.
- **A lookup says GitHub could not be reached.** GitHub limits unauthenticated reads to 60 an hour for each address. Answers are cached for 5 to 10 minutes. If it happens often, add a read-only token with `npx wrangler secret put GITHUB_TOKEN`.
- **A leaked webhook address.** Run `serverkit apply --rotate-webhook Reports`, then store the new address with `sync-secrets` or step 7.

## Tests

```bash
npm test
```

The tests run under Node's own test runner and not inside the Workers runtime. The worker has no Workers-only bindings. It uses `fetch` and Web Crypto, which Node provides, so a plain unit test covers every path with a fresh key pair made at test time. We also ran the built bundle once in the local Workers runtime to confirm that the signature check works there.
