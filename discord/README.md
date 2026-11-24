# Discord

The PHAEMOS community server, built from one layout file by a script. Nothing is clicked together by hand except a short list of settings that Discord keeps behind a person's own sign-in.

> [!NOTE]
> This folder is published to [phaemos/discord](https://github.com/phaemos/discord) as a read-only copy. Open issues and pull requests on [phaemos/phaemos](https://github.com/phaemos/phaemos). Paths below are relative to this folder.

> [!IMPORTANT]
> The bot needs more permissions than the first invite gave it: Pin Messages (Discord split it from Manage Messages), Create Private Threads and Connect, Speak, Stream and Use Voice Activity for the voice channels, plus Mute Members, Move Members and Request to Speak so it can give the staff roles their stage moderation on Town hall. Authorise the bot again once with `python3 -m serverkit invite-url --layout layout/phaemos.toml --no-staff-setup` or switch those nine on by hand on the bot's role in Server Settings, Roles. Until then `plan` stops at the preflight and names what is missing.

## What is here

| Piece | Where | What it does |
| --- | --- | --- |
| The script, `serverkit` | `serverkit/` | Reads a layout file and makes the server match it. Standard library only. Plans first and changes nothing until told to |
| The layout and the texts | `layout/`, `texts/`, `content/` | One TOML file describes the roles, channels, rules, onboarding and moderation. The texts are plain Markdown files. `content/commands.toml` holds what the slash commands say |
| The relay | `relay/` | Posts GitHub releases, issues, merged changes, discussions and announcements into the server. It runs in GitHub Actions. See [what reaches the feed](#what-reaches-the-feed) |
| The worker | `worker/` | Answers the slash commands from Cloudflare Workers. See [worker/README.md](worker/README.md) |
| The tests | `tests/` | A fake Discord on 127.0.0.1 and the tests that use it. Nothing here ever talks to Discord |

No id, token, webhook address or invite link is ever written in this folder. The script finds everything by name each time it runs and reads secrets from the environment.

## What you need

- Python 3.12 or later (`python3 --version`)
- Node 24 and npm, for the worker
- The `gh` tool, signed in (`gh auth status`), with admin rights on the repository
- A Discord account and a free Cloudflare account
- A Mac. Commands below are for macOS and Linux shells

## Set it up from nothing

Do the steps in order. Each one says what to click or type. Run commands from this folder.

1. **Turn on two-factor sign-in.** Discord, User Settings, My Account, then enable two-factor authentication. Discord asks for it before a bot can hold strong permissions in a server that requires it for moderation.
2. **Create the server.** Press the plus button at the bottom of the server list, choose Create My Own, then For a club or community. The name must be exactly the `name` under `[server]` in `layout/phaemos.toml`, which is `PHAEMOS`.
3. **Enable Community.** Server Settings, Enable Community. Accept the safety settings and let Discord create the rules channel and the updates channel. This is by hand because Discord only lets an Administrator switch it on and the script never holds that permission.
4. **Create the application.** Open <https://discord.com/developers/applications> and press New Application. Name it `PHAEMOS Bot`. On the Bot page turn Public Bot off and leave all three privileged intents off. Press Reset Token and copy the token once. Do not paste it anywhere yet.
5. **Keep the token out of files and shell history.** Store it in the macOS keychain. The command asks for the token itself, so it is never typed into the command line and never saved in your history:

   ```bash
   security add-generic-password -s phaemos-discord-bot -a bot -w
   ```

   Paste the token at the prompt. In each new terminal session load it for the commands that follow:

   ```bash
   export DISCORD_BOT_TOKEN="$(security find-generic-password -s phaemos-discord-bot -a bot -w)"
   ```

   Never put it in a `.env` file, a script or a chat. `.env.example` lists the names only. The script does not read a `.env` file.
6. **Invite the bot.** This prints a link that asks for what the layout needs and, for the next step, what it takes to set the two staff roles up. It never asks for Administrator, Kick, Ban or Mention Everyone:

   ```bash
   python3 -m serverkit invite-url --layout layout/phaemos.toml
   ```

   Open the link, choose the server and authorise. For a smaller invite that only covers `plan` and `apply`, add `--no-staff-setup` and make the roles by hand instead (see the alternative below).
7. **Set the two staff roles up.** Maintainer and Moderator are the owner's. The bot makes them once, from the layout, with every permission it holds. Then you take the bot's ability to touch them away by moving them above its own role. First look at what it would do, then do it:

   ```bash
   python3 -m serverkit staff-roles --layout layout/phaemos.toml
   python3 -m serverkit staff-roles --layout layout/phaemos.toml --apply
   ```

   It creates each role if it is missing or fills it in while it sits below the bot's role and leaves a role that is at or above the bot's alone. It never gives either role to anyone, moves it, renames it or deletes it. Running it twice changes nothing. It ends with a numbered list for you. Do it now, in that order:
8. **Drag the roles above the bot and finish them by hand.** In Server Settings, Roles:
   1. Drag Maintainer and Moderator above the bot's role. **Until this is done, anyone holding the bot's token could edit them.** From here Discord itself stops the bot editing or granting them.
   2. Switch on by hand what the bot could not set. For Maintainer, switch on the permission to kick, approve and reject members, the permission to ban members and the permission to mention everyone. The list the command printed names anything else.
   3. Give yourself the Maintainer role. Once the worker knows staff by role, an owner who does not hold it is refused `/mod`.

   The alternative, for anyone who prefers the bot never to touch these roles: skip `staff-roles`, ask for the smaller invite and make them yourself. In Server Settings, Roles press Create Role twice, then drag them above the bot's role:
      - `Maintainer`: switch on exactly `kick_members`, `ban_members`, `view_audit_log`, `manage_messages`, `mention_everyone`, `manage_nicknames`, `manage_events`, `manage_threads`, `moderate_members`, `create_events`, `send_polls`, `pin_messages`, `bypass_slowmode`. Also switch on Display role members separately.
      - `Moderator`: switch on exactly `manage_messages`, `manage_nicknames`, `moderate_members`, `pin_messages`. Also switch on Display role members separately.
   Then give yourself Maintainer.
9. **Read the plan.** Nothing is changed by this command:

   ```bash
   python3 -m serverkit plan --layout layout/phaemos.toml
   ```

   The preflight checks the bot's position: below Maintainer and Moderator and above the roles it manages. It refuses to run until the drag is done, which is what closes the window. The plan also compares both staff roles with the layout and prints every difference as a numbered owner step.
10. **Apply.**

   ```bash
   python3 -m serverkit apply --layout layout/phaemos.toml
   ```

   Every channel and category in the layout is created by this first apply. Run the plan again. It should end with `Summary: nothing to change`. Discord made its own `moderator-only` channel when you enabled Community. The bot cannot see it, so the script makes its own and points Community at that one. You can delete Discord's copy by hand afterwards.
11. **Three settings by hand.** In Server Settings: turn on Rules Screening and paste what `python3 -m serverkit rules-text --layout layout/phaemos.toml` prints. Turn on the two-factor requirement for moderation. Under Invites create one invite that never expires. Share only that one. In Safety Setup switch on Raid Protection and the CAPTCHA for suspicious joins and set a DM and invite pause plan for a raid (see When something goes wrong). The names of these screens are unconfirmed.
12. **Deploy the worker.** Follow [worker/README.md](worker/README.md). In short:

    ```bash
    cd worker
    npm ci
    npx wrangler login
    npm run deploy
    ```

    Use `npm run deploy` and not `npx wrangler deploy`: it runs the checks and builds the content first. Note the address it prints.
13. **Create the GitHub environment.** Open <https://github.com/phaemos/phaemos/settings/environments>, press New environment and name it `community`, then press Configure environment. Under Deployment branches and tags choose Selected branches and tags. Branch and tag rules are separate, so add two:

    1. Press Add deployment branch or tag rule, set Ref type to Branch, type `main` and press Add rule.
    2. Press Add deployment branch or tag rule again, set Ref type to Tag, type `v*` and press Add rule.

    The secrets for the relay belong in this environment and never in the repository's own secrets.
14. **Store the secrets.** This reads each webhook address from Discord and stores it without showing it. The environment secrets are `DISCORD_WEBHOOK_ANNOUNCEMENTS`, `DISCORD_WEBHOOK_RELEASES`, `DISCORD_WEBHOOK_FEED`, `DISCORD_WEBHOOK_IDEAS`, `DISCORD_WEBHOOK_RESEARCH` and `DISCORD_WEBHOOK_CI_ALERTS`, plus `DISCORD_TAG_IDEAS` and `DISCORD_TAG_RESEARCH`, the ids of the From GitHub tag in each of those two forums. A forum that requires a tag refuses a post without one, so the relay reads the id from its secret and the workflow must pass both secrets to the relay step. The `Reports` and `Tickets` addresses, the ticket tag ids and the application's public key go to Cloudflare as secrets for the worker. So does `STAFF_ROLE_IDS`: the script looks up the Maintainer and Moderator roles by name, sends their ids to `wrangler` on standard input and prints only the role names and a count. If either role does not exist yet it stops and stores nothing:

    ```bash
    python3 -m serverkit sync-secrets --layout layout/phaemos.toml
    ```

15. **Connect the commands.** The worker is already deployed, which is the order to keep whenever commands change: deploy the worker, then apply. Give the script the worker's address and apply again:

    ```bash
    export DISCORD_INTERACTIONS_URL="<the worker address>/interactions"
    python3 -m serverkit apply --layout layout/phaemos.toml
    ```

16. **Check it.** Type `/help` in the server. On GitHub open Actions, choose the Discord relay workflow, run it by hand with `dry_run` turned on and read its output. Then run it once with `dry_run` off if you want a first post.
17. **Reset the token.** On the Bot page press Reset Token. The old token stops working. Store the new one in the keychain the next time you need the script. This is the last step of every session, see [Every session](#every-session).
18. **Before the invite is published.** The privacy and conduct edits for the community server must be on the project's own pages first. Then put the invite in `README.md` and `SUPPORT.md` of the main repository.

### What only you can do by hand

These are the things Discord does not let a bot do. In order:

1. Create the server.
2. Enable Community.
3. Run `staff-roles`, drag Maintainer and Moderator above the bot's role, switch on the three permissions it could not set and give yourself Maintainer.
4. Create the application and invite the bot.
5. Drag the bot's role below Maintainer and Moderator and above the roles it manages.
6. Switch on Rules Screening and paste the rules.
7. Switch on the two-factor requirement for moderation.
8. Give yourself Maintainer. Give Maintainer, Moderator and Contributor to people.
9. Create the one public invite. Switch on Raid Protection and the CAPTCHA for suspicious joins in Safety Setup.
10. Optional: limit commands to some channels, set up the Server Guide and upload the server icon.

## What the server holds

| Setting | Value | Why |
| --- | --- | --- |
| `system_channel` | `welcome` | Discord writes its own join message here. The bot has no gateway connection and cannot see joins, so this is the only way to greet a member |
| `system_channel_flags` | 6 | `SUPPRESS_PREMIUM_SUBSCRIPTIONS` (`1 << 1`) hides boost notices and `SUPPRESS_GUILD_REMINDER_NOTIFICATIONS` (`1 << 2`) hides setup tips. `SUPPRESS_JOIN_NOTIFICATIONS` (`1 << 0`) and `SUPPRESS_JOIN_NOTIFICATION_REPLIES` (`1 << 3`) are not set, so a join is announced and the wave reply stays |

A join message announces each member by name, which is why it has its own channel: `start-here` stays read-only with its pinned messages and `welcome` is read-only too, so it is only ever a list of arrivals. Members can react there and nobody can write. Discord's developer documentation does not say whether the wave sticker reply needs Send Messages in the channel it is sent to. The reply is a message the member's own client sends, so it may be refused in a read-only channel (unconfirmed). If the buttons do nothing, set `system_channel_flags` to 14 to hide them or let members send in `welcome`.

| Category | Channel | Kind | Members | Notes |
| --- | --- | --- | --- | --- |
| Start here | `welcome` | text | read, react | First in the category. Discord's join messages, one for each member |
| Start here | `rules` | text | read | Plain text, pinned, so a member with embeds off still reads it |
| Start here | `start-here` | text | read | The branded embed with the banner, pinned |
| Start here | `announcements`, `releases` | announcement | read | Fed by the relay |
| Start here | `service-status` | announcement | read | Notices about the hosted service. `/status` reads its status address and says plainly when that is not live yet |
| Resources | `docs` | text | read | Pinned links: documentation, FAQ, roadmap, contributing |
| Community | `general` | text | post | Five second slow mode |
| Community | `bot-commands` | text | post, use commands | A place to try the slash commands. Five second slow mode. A pinned plain message lists every command as a link with one line each, built from `content/commands.toml` so it cannot go stale |
| Community | `showcase` | forum | post | A pinned Read first post |
| Community | `ideas`, `research` | forum | post | One post for each new GitHub discussion in Ideas and Research, made by the relay, each with a pinned Read first post that says the GitHub discussion is the record and the forum is for talking it through |
| Community | `introductions`, `off-topic` | text | post | A place to say hello and a place for everything else. `off-topic` has a five second slow mode |
| Support | `help`, `hardware` | forum | post | Each has a pinned Read first post with the guidelines, the FAQ (from `content/commands.toml`) and a reply time of two days |
| Support | `private-help` | text | read | Staff open a private thread here for a ticket. Members cannot open private threads. Moderators can, only here |
| Contributing | `contributing`, `github-feed` | text | post, read | The feed is posted by the relay |
| Staff | `moderator-only`, `mod-log`, `ci-alerts` | text | hidden | `ci-alerts` is fed by a CI webhook you wire up later |
| Staff | `tickets` | forum | hidden | One post for each `/ticket`, with a status tag |
| Staff | `staff-voice` | voice | hidden | Calls between staff, with screen sharing |
| Voice | `Workbench` | voice | talk | Open voice with voice activity and screen sharing on, so nobody is held to push-to-talk |
| Voice | `Town hall` | stage | listen, request to speak | Maintainer and Moderator can run it: manage the channel, mute and move speakers, on this stage only |

Every channel and category is created on the first apply. Nothing is held back. A layout can still hold one back, which is a feature of the tool and not of these files: give a channel `enabled = false` with a `threshold` such as `"50 members"` and the plan shows it as `deferred` until you switch it on. The Ideas and Research forums sit in the Community category, since they are for talking and a new category for two channels would only add a heading. Polls stay out: members cannot send polls and Discord's own poll in `general` is held by Maintainers, so a polls channel would add nothing.

**Private threads.** The developer documentation says private threads can only be made in text channels and says nothing about a server boost level or a feature flag, so `plan` does not check for one. Make a test private thread in `private-help` once before the invite goes out. If Discord refuses, tell us.

**Events.** Discord scheduled events are one-off and not part of the server's state, so the tool does not create them. To hold a demo or a question session: Server Settings, Events, Create Event, choose Town hall or Workbench and give it a date. Do this by hand.

**Onboarding and auto moderation limits.** `check` refuses what Discord refuses, before anything is sent. Onboarding needs at least 7 default channels and at least 5 that @everyone can write in. A forum is assumed not to count towards the five, because the first live apply was refused with 10 defaults of which only 2 were plain channels members could write in. Defaults and the channels an answer adds must be text, announcement or forum channels that members can see. Auto moderation allows 10 regex patterns of 260 characters at most, in Rust syntax: no lookaround and no backreference and no `\w`, `\d`, `\s` or `\b` inside a counted repeat such as `{10,}`, since in Rust they mean all of Unicode and compile to something large. Write `[A-Za-z0-9_]` instead. When Discord refuses a request with 400 the tool prints each field path with Discord's code and message, with ids and long tokens masked, so the next failure names the field.

## Tickets and commands

`/ticket` opens a form for a kind from the server's list (Account, Privacy, Conduct or Other), a short subject and the details. The worker posts it through the `TICKETS_WEBHOOK_URL` secret into the staff `tickets` forum as one post with the kind as its tag and answers the member privately with what happens next and the two day reply time. The details are never repeated in a public message. A member is limited to one ticket in ten minutes. That limit is kept in the memory of each running copy of the worker, so it is per isolate and best effort: a second copy counts for itself. The allowance is given back only when Discord certainly refused the post. After a timeout the member is told to wait ten minutes and then write to the contact address, because the post may have been made. A form that Discord delivers twice is posted once. Staff open a private thread for the member in `private-help`. The worker holds no bot token.

`/issue show` looks an issue up by number and `/issue new` says where to report a bug, a feature, a hardware problem or a docs problem on GitHub. They replace `/issue` and `/bug`. The layout lists `bug` under `retired` in `[commands]`, so the next `apply` removes the old command. Only a name listed there is ever removed this way.

`sync-secrets` stores `TICKETS_WEBHOOK_URL` for the worker and `TICKET_TAG_IDS`, the id of each ticket kind's forum tag, on standard input. It never prints either.

## The relay

A new issue labelled `good first issue` is posted with its own lead, "Good first issue". Questions, builds and polls from GitHub Discussions reach `github-feed` with their category in words, such as "New question in Q&A". A new discussion in Ideas or Research becomes a forum post in `ideas` or `research`, named from the discussion's title, with the link to GitHub in the post. A route in `[relay.discussions]` with `thread = true` posts into a forum and names the post. A failed run on the default branch posts an alert to the staff `ci-alerts` channel through `DISCORD_WEBHOOK_CI_ALERTS`, from a last job in the CI workflow that runs `python3 discord/relay/post.py --layout discord/layout/phaemos.toml --ci-failure`. It never alerts a pull request and copies no log, workflow name or other text from the run. The pinned roadmap message in `contributing` holds links to GitHub's own current pages, so it never goes stale and needs no job.

## The start messages

The files in `texts/` are posted in the channels the layout names, in order and edited in place by later runs, so a link to one keeps working. Each channel says how its messages look in the layout:

| Key | Meaning |
| --- | --- |
| `style = "plain"` | The default. The file is the message, with link previews off |
| `style = "embed"` | The file's first line is the title of an embed and the rest is its description. The accent colour is the brand's, with the organisation's mark as a small thumbnail |
| `banner = true` | The first message of the channel also carries the banner image |
| `pin = true` | The managed messages are pinned, in order. The notice each pin leaves is removed |

`#start-here` uses `embed`, `banner` and `pin`. `#rules` is plain and pinned, so a member with embeds switched off still reads the rules. `#docs` is an embed. Everything else stays plain.

A forum can carry `read_first = "texts/readfirst-help.md"`. The file's first line is the post's name and `{guidelines}` and `{faq}` are filled in from the forum's guidelines and from the `[[faq]]` entries of the command content. The tool posts it as a pinned forum post with a moderated Read first tag and later runs edit it in place.

**Links by id.** Write `{channel:help}`, `{role:Moderator}` or `{command:help}` in a text and the script posts a clickable `<#id>`, `<@&id>` or `</help:id>`. The ids are looked up when the script runs, so a link keeps working when a channel, role or command is renamed. `{command:mod guide}` links a subcommand. A name that is not in the layout fails `check`. A channel or command that waits (a channel that a layout holds back or a command that is not registered yet) is written as plain words until it exists. No message ever pings: every post and edit sends empty allowed mentions, a role link included. Headings are written `### Heading` in the files. A plain message shows them in bold and an embed uses Discord's own heading.

**The images.** They are uploaded with the message as attachments and referenced with `attachment://`, never linked from a web address. They are copies kept in `assets/` so this folder stands alone:

| File here | Copied from the repository's `assets/brand/` | Size | Use |
| --- | --- | --- | --- |
| `assets/banner.png` | `phaemos-social-preview.png` | 1280 by 640, 118,510 bytes | The banner, 2 to 1, which Discord shows best |
| `assets/logo.png` | `phaemos-emblem-mono.png` | 1024 by 1024, 178,323 bytes | The thumbnail, the organisation's avatar |

The accent colour in `[brand]` is the primary blue from `assets/brand/README.md`. The file name Discord stores carries a short hash of the image, such as `banner-1a2b3c4d.png`. A later run compares those names with the files, so a changed image is noticed from its content and not from a web address Discord returns and only that message is edited, in place.

**Limits.** `check` fails a text that could pass Discord's limits: an embed title of 256 characters, a description of 4096 and all the text of one message together 6000 and 2000 for a plain message. It counts every link at its full length. The banner must be near 2 to 1 and an image may be a PNG, JPEG, WebP or GIF.

**Accessibility.** Every word is in the text of the message and never only in an image. The banner and the mark are decoration. The colour carries no meaning. Headings and lists are Discord's own markdown, so a screen reader gets the structure. The text sits on Discord's own embed background, so it reads in both themes. The one limit that cannot be closed: a member who has switched off embeds in their own settings sees no embed at all. For a message that must reach everyone, set that channel to `style = "plain"`. Plain is the default so nothing changes unasked.

**Pins.** The pin list shows the newest pin first in Discord's client, so the messages are pinned last to first and read in order from the top. The documentation does not state the order, see First real run. The script only ever unpins its own messages and only to put them back in order. It never touches a pin it did not make and a second run changes nothing. For Rules Screening, which takes no links by id, run `python3 -m serverkit rules-text --layout layout/phaemos.toml` and paste what it prints.

## What reaches the feed

Releases and announcements are posted as soon as they are published. A new issue or discussion is posted to the feed at once only when its author is an owner, a member or a collaborator of the repository. From anyone else it waits until a maintainer acts: for an issue, a label from the allow-list added by someone with write access and for a discussion, a maintainer's first comment. The feed also holds back anything past ten posts in any hour and says in one line how many were held.

## Every session

The bot holds strong permissions for as long as its role is raised. Its token stays valid until it is reset. So each session that used it ends the same way:

1. Run the commands you need.
2. **Lower the bot's role.** Run `python3 -m serverkit stand-down` for the steps. It is by hand because Discord only lets a bot edit roles below its own highest role, so a bot cannot lower itself. Before the next change run `python3 -m serverkit stand-down --raise` for the permissions to switch back on.
3. **Check it.** Run `python3 -m serverkit session-check` with the token still set. It says plainly whether the role is still raised and exits 3 if it is.
4. **Reset the bot token.** Open <https://discord.com/developers/applications>, choose the application, open Bot and press Reset Token. The old token stops working at once. Store the new one in the keychain only when you next need it. The tool cannot see whether this is done.

`apply`, `lockdown`, `purge-mod-log` and `sync-secrets` finish by printing this list. Slash commands and the relay do not use the token, so they keep working.

## What a stolen token can do

`staff-roles` is the only command that ever writes Maintainer or Moderator. Only while the role sits below the bot's role. `plan` and `apply` never do. Once you have dragged the two roles above the bot's role, Discord itself stops the bot editing or granting them. The bot holds exactly these 26 permissions, worked out from the layout: `manage_channels`, `manage_guild`, `add_reactions`, `stream`, `view_channel`, `send_messages`, `manage_messages`, `embed_links`, `attach_files`, `read_message_history`, `connect`, `speak`, `mute_members`, `move_members`, `request_to_speak`, `use_vad`, `change_nickname`, `manage_roles`, `manage_webhooks`, `use_application_commands`, `manage_threads`, `create_public_threads`, `create_private_threads`, `send_messages_in_threads`, `moderate_members`, `pin_messages`. It never holds Administrator, Kick Members, Ban Members, Mention Everyone or View Audit Log. The invite for `staff-roles` asks for 6 more, the permissions the two staff roles carry apart from kick, ban and mention everyone, so the bot can set them. Lower the role with `stand-down` once you are done.

There is one window. Between running `staff-roles` and dragging the two roles above the bot's role, the roles sit below the bot, so anyone holding the token could edit them. Do the drag straight away. `plan` and `apply` refuse to run until it is done, so the window cannot be left open by accident and resetting the token closes it too. After the drag, with a valid token someone could:

- Delete, edit and hide any channel or category and change channel overwrites, including opening the staff channels to everyone. Whether Discord lets a bot write an overwrite for a role above its own is not documented, see First real run.
- Change server settings: verification level, notifications, the rules, updates, safety and system channels, onboarding and every auto moderation rule.
- Create and delete webhooks and read the address of each one, which lets them post as the feed, the announcements or the reports webhook.
- Change the application's interactions address, which sends the slash commands to a server of theirs.
- Create, edit, delete and grant roles below the bot's own: Contributor and the interest roles. Edit what `@everyone` holds, up to the permissions the bot holds, which includes Manage Channels, Manage Roles and Manage Server.
- Delete other people's messages and threads and time out members whose highest role is below the bot's.
- Post as the bot, with mentions still switched off by default but not enforced on a stolen token.

They could not:

- Kick or ban anyone, ping everyone, read the audit log or hold Administrator, because the bot lacks those permissions and a bot can only grant what it holds.
- Edit, delete, reorder or hand out Maintainer, Moderator or any role above the bot's, so they cannot give their own account staff powers or the owner's kick and ban.
- Change the Community setting, which needs Administrator.

All of this ends when the token is reset, which is why every session finishes with the closing list above. Lowering the bot's role to nothing between sessions also leaves a token that leaked earlier with no permissions at all.

## First real run

Some things cannot be known until you run it against the real Discord. None can do harm. Look for these:

| Unknown | What the script does | What to look for |
| --- | --- | --- |
| Whether Discord applies the parent channel rule as documented (a bot may only allow or deny in a channel what it holds in the parent category) | The layout gives the bot's row on each category every bit that its channels name, so it holds them. If Discord is stricter, a write stops with exit 1 | A 403 on a channel write, with a hint about the bot's row on the category |
| Whether forums count towards the five channels onboarding needs | Saves the questions with onboarding off, then tries to switch it on | Exit 3 with the advanced-mode advice in the output |
| What the Community template creates | Adopts `rules` by name. Discord's own `moderator-only` is hidden from the bot, so a second one is made | Two channels named `moderator-only`. Delete Discord's by hand afterwards |
| Whether webhooks made by the bot carry its application id | Matches managed webhooks by that id and name | A second run that wants to create the webhooks again. If so, tell us |
| Whether Discord lets the bot write a channel overwrite for a role above its own (the channel page says nothing about role order for overwrites) | Writes the rows for Maintainer and Moderator like any other | A 403 on a staff channel. If it happens, add those two rows by hand and tell us |
| Whether a moderator can time out a maintainer | Nothing. The role order is set so Maintainer is above Moderator | Try it once with two test accounts |
| Whether private threads still need a boost level or a feature | Nothing is checked, the documentation is silent | Open a private thread in `private-help` as a Moderator before launch |
| Whether Discord accepts moving a role that ties with the bot's own and which way it sorts equal places (the documentation says only that equal places sort by id) | A tie is reported in the plan and the roles are placed below the bot in one request | A refused request in the role order step. Drag the roles by hand |
| Whether Discord draws the Safety Setup names as written | Not applicable, by hand | The screen names in the checklist |
| Whether the pin list shows the newest pin first and whether the API lists pins as a page of items with a `pinned_at` time | Pins last to first so the first message reads first and removes the notice each pin leaves | The pin list in `#rules` reading in the wrong order. Flip `PIN_NEWEST_FIRST` in `serverkit/engine.py` |
| Whether Discord draws `###` headings inside an embed description | Writes them as the files say | A heading shown as plain `###`. Set that channel to `style = "plain"` |
| Whether an edit that keeps an uploaded image by its id is accepted | Keeps the image when only the text changes and uploads again only when the image changes | A refused edit. Tell us |
| Whether an alert-only rule is accepted for member profiles | Creates the Impersonation rule with an alert and no block | A refused rule in the output |

## Reading a plan

Every line starts with a word, so nothing depends on colour. Colour is off unless you pass `--colour` and `NO_COLOR` is honoured.

| Word | Meaning |
| --- | --- |
| `ok` | A check passed |
| `create` | Something will be made |
| `update` | Something that exists will be changed to match the layout |
| `rename` | An object will take a new name. Held back unless you pass `--allow-renames` |
| `delete` | Only shown with `--prune`. Needs the typed server name |
| `rotate` | Only shown with `--rotate-webhook`. A webhook is replaced and gets a new address |
| `blocked` | Waiting for you to act by hand, usually to enable Community |
| `deferred` | A channel that a layout keeps switched off until the server grows. These layouts hold nothing back |
| `ready` | A deferred channel whose threshold has been reached. Set `enabled = true` in the layout |
| `unmanaged` | Something a person made. It is listed and left alone |
| `warning` | An unmanaged overwrite on a private channel, which may be a leak |

The server is found by name: the script takes the server whose name equals `name` under `[server]`. A server with any other name is never touched.

## Commands and flags

| Command | What it does |
| --- | --- |
| `check` | Validates the layout, the texts and the command content. No network. Runs in CI |
| `plan` | Prints the plan and changes nothing. The default when no command is given |
| `apply` | Prints the plan, then makes the changes |
| `invite-url` | Prints the link that adds the bot with exactly the permissions the layout needs |
| `sync-secrets` | Stores each webhook address and the application's public key under its secret name, using `gh` and `wrangler`. Nothing is printed |
| `export-content` | Writes the command content as JSON for the worker. `--check` fails when the file is out of date |
| `lockdown` | Pauses invites and direct messages for up to 24 hours. `--lift` ends it |
| `purge-mod-log` | Deletes entries in `mod-log` and `moderator-only` older than `--older-than`, with the threads in them where reports are handled, after confirmation |
| `staff-roles` | Sets up Maintainer and Moderator once from the layout, with the permissions the bot holds. A dry run unless `--apply` is given. Never gives a role to anyone, moves, renames or deletes one. Ends with the owner list |
| `rules-text` | Prints the first rules message as plain text, for pasting into Rules Screening. No network |
| `session-check` | With a token, says plainly whether the bot's role is still raised. Exit 0 when lowered, 3 when not. Only reads |
| `stand-down` | Prints the steps to lower the bot's role to nothing between layout changes. `--raise` prints the permissions to switch back on. Only reads and only if a token is set |

| Flag | Meaning |
| --- | --- |
| `--layout` | The layout file. Optional when `layout/` holds exactly one |
| `--only roles,channels` | Limit the run to some steps: `settings`, `roles`, `channels`, `pointers`, `automod`, `onboarding`, `commands`, `messages`, `pins`, `webhooks`, `application` |
| `--allow-renames` | Apply the renames the plan shows. Needs the typed server name |
| `--prune kind` | Delete unmanaged objects of one kind: `channels`, `roles`, `overwrites`, `automod`, `webhooks`, `messages` or `commands`. One kind in each run. Needs the typed server name |
| `--rotate-webhook name` | Delete one managed webhook and create it again. Follow with `sync-secrets`. Needs the typed server name |
| `--format text` or `json` | Output form |
| `--colour` | Add colour to the words |
| `--max-wait seconds` | Cap on waiting for rate limits. Default 900 |
| `--no-summary` | Do not post the run summary in `mod-log` |
| `--hours`, `--lift` | For `lockdown` |
| `--raise` | For `stand-down` |
| `--apply` | For `staff-roles`: make the changes. The default is a dry run |
| `--no-staff-setup` | For `invite-url`: ask only for what `plan` and `apply` need |
| `--older-than 365d` | For `purge-mod-log`. Days or hours such as `48h` |
| `--check` | For `export-content` |

Anything that deletes or renames lists exactly what will happen and asks you to type the server's name. Any other answer cancels. With no terminal to type on it refuses to run. There is no flag that skips the question. Deleting a channel cannot be undone.

The environment variables are `DISCORD_BOT_TOKEN` (every command that talks to Discord), `DISCORD_GUILD_ID` (only to pick between two servers of one name), `DISCORD_INTERACTIONS_URL` (the worker's address) and `DISCORD_API_BASE` (tests only, refused unless the host is localhost or 127.0.0.1).

Every change carries an audit log reason of the form `PHAEMOS layout <8 characters of the layout file's hash>: <what>`. The audit log then says which version of the layout made each change.

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Done. The server matches the layout and nothing is waiting |
| 1 | Stopped by an error. Some changes may have been made. Run it again to resume |
| 2 | Could not start: bad arguments, an invalid layout, no token, a refused token, the server not found, the bot's role in the wrong place, a permission missing or a cancelled confirmation |
| 3 | Finished what it could. Something is blocked until you act by hand |
| 4 | `plan` only: changes are waiting |

When several apply the lowest number other than 0 wins.

## Day to day

- **Change the layout.** Edit `layout/phaemos.toml`, open a pull request and merge it. Then run `plan` and `apply`.
- **Rename something.** Add the old name to `previous_names` on the object, run `plan`, then `apply --allow-renames`.
- **Switch on a waiting channel.** Only a layout that holds a channel back has one. When the plan shows `ready`, set `enabled = true` on it and apply.
- **Change a command.** Edit `content/commands.toml`, then run `python3 -m serverkit export-content`. Deploy the worker first (`npm run deploy` in `worker`) and apply after: `apply` registers the new commands at once and a worker that has not been deployed yet answers them with an error.
- **Give someone a role.** In Server Settings, Members, add Maintainer, Moderator or Contributor by hand. No bot holds Manage Roles for people.

## Routine

- Each week look at the Actions tab for a red relay run and read `mod-log`.
- Four times a year run `python3 -m serverkit purge-mod-log --older-than 365d`.

## When something goes wrong

- **A leaked bot token.** Reset it on the Bot page at once. Commands and the relay keep working because they do not use it. A token that leaked earlier and was never reset is still valid.
- **A leaked webhook address.** Run `python3 -m serverkit apply --rotate-webhook "<name>"`, then `sync-secrets`.
- **A raid.** In this order. First use Discord's own Pause Invites in Server Settings, Safety Setup: it needs no bot. Time out the accounts that are posting. Only if you need more, raise the bot's role (`python3 -m serverkit stand-down --raise`), run `python3 -m serverkit lockdown --hours 6`, lift it later with `--lift`, then lower the role and reset the token. `lockdown` needs Manage Server, which the bot does not hold while it is stood down.
- **The bot was removed.** Invite it again with `invite-url`, drag its role below Maintainer and Moderator and apply.
- **Onboarding is refused.** Set `mode = "advanced"` under `[onboarding]`. If it is still refused make `showcase` a text channel and switch on `introductions`.

## What is never in this folder

Ids, tokens, webhook addresses, the invite link and people's names. A test fails if any file here holds a run of 17 to 20 digits, a webhook address or something shaped like a token.

## Running the tests

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/pytest
.venv/bin/python -m serverkit check --layout layout/phaemos.toml
.venv/bin/python -m serverkit export-content --layout layout/phaemos.toml --check
```

The tests start a fake Discord on 127.0.0.1. It refuses what Discord refuses: permission rules, role order, channel kinds, limits, rate limits and failures half way. Nothing reaches Discord, GitHub or Cloudflare.

## Licence

GNU Affero General Public License v3.0, see [LICENSE](LICENSE).
