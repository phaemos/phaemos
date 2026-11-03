# Discord

The PHAEMOS community Discord server, built by script so it can be recreated at any time. The bot planned for the server lives here too.

> [!NOTE]
> This folder is published to [phaemos/discord](https://github.com/phaemos/discord) as a read-only copy. Open issues and pull requests on [phaemos/phaemos](https://github.com/phaemos/phaemos).

An organisation-run server is planned. Until it opens, [GitHub Discussions](https://github.com/phaemos/phaemos/discussions) is the place to talk. The invite link goes into the main README and SUPPORT.md once the server exists.

## What the script builds

`setup_discord.py` takes an empty server to the full PHAEMOS layout and changes nothing on a second run.

| Category | Channels |
| --- | --- |
| PHAEMOS | #announcements (Admin and Maintainer post, everyone reads), #general, #releases |
| Support | #help, #bugs, #feature-requests |
| Hardware | #esp32, #stm32, #arduino-nano, #pico-w |
| Community | #show-and-tell, #ideas |
| Admin (hidden) | #bot-logs, #moderation |

Roles, highest first: Admin with full permissions, Maintainer who can manage messages, pin and manage threads, Contributor which marks a merged pull request or an accepted issue and carries no extra rights, Member as the default and Bot, which the script gives to every bot account it finds. Only Admin, Maintainer and Bot see the Admin category.

It finishes by posting a summary to #bot-logs: every role and channel id, invite links for Ticket Tool (ticket panels in #help and #bugs) and Carl-bot (the welcome message and the default role) and the steps left to do by hand. Running it again after inviting those bots gives them the Bot role.

## What it needs

- Python 3.12 (the version the backend uses) with `discord.py`, pinned in [`requirements.txt`](requirements.txt).
- A Discord application with a bot, created in the [Discord developer portal](https://discord.com/developers/applications), with the Server Members and Message Content intents turned on.
- The bot invited to the server with Administrator permission for the first run. The summary says how to narrow it afterwards.
- Two environment variables: `DISCORD_BOT_TOKEN` holds the bot's token and `DISCORD_GUILD_ID` the server id (turn on Developer Mode in Discord, then right-click the server icon). The script reads both from the environment only.

## Running it

```bash
pip install -r discord/requirements.txt
DISCORD_BOT_TOKEN=... DISCORD_GUILD_ID=... python discord/setup_discord.py
```

To keep both values in `backend/.env` instead, fill in the two keys there and load the file first:

```bash
set -a && . backend/.env && set +a
python discord/setup_discord.py
```

It prints each change it made or `No changes` when the server already matches. The token is the bot's password: keep it in `.env`, never in a commit.

## The bot that is planned

A bot of the organisation's own is the next thing in this folder: slash commands for members, relays that post releases, discussions and critical alerts into the right channels and the server's channels, roles and rules kept in code, so the setup script and the bot share one definition. Progress is tracked under the [Community: Discord server](https://github.com/phaemos/phaemos/issues/256) issue.

## Licence

GNU Affero General Public License v3.0, see [LICENSE](LICENSE).
