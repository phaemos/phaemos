# Scripts

Maintainer scripts for the project's own services, not part of the application runtime.

| File | Purpose |
|---|---|
| setup_discord.py | Builds the PHAEMOS Discord server: roles, categories, channels and their permissions, then posts every id, the Ticket Tool and Carl-bot invite links and the steps left to do by hand to #bot-logs. Running it again changes nothing. |

## Discord server

Before the first run:

1. Create a Discord server named PHAEMOS.
2. Create an application with a bot in the [Discord developer portal](https://discord.com/developers/applications) and store its token as `DISCORD_BOT_TOKEN`.
3. Turn on the Server Members and Message Content intents in the bot settings.
4. Invite the bot with Administrator permission, which can be narrowed after the first run.
5. Copy the server id (turn on Developer Mode, then right-click the server icon) and store it as `DISCORD_GUILD_ID`.

Then:

```bash
pip install -r scripts/requirements.txt
DISCORD_BOT_TOKEN=... DISCORD_GUILD_ID=... python scripts/setup_discord.py
```

The script reads both values from the environment only. To keep them in `backend/.env` instead, fill in the two keys there and load the file first:

```bash
set -a && . backend/.env && set +a
python scripts/setup_discord.py
```

It prints each change it made, or `No changes` when the server already matches. Run it again after inviting Ticket Tool and Carl-bot so they get the Bot role.
