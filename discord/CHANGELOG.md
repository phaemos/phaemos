# Changelog

## Unreleased

### Added

- `serverkit staff-roles`, which sets up Maintainer and Moderator once from the layout with the permissions the bot holds, as a dry run unless `--apply` is given. It is the only command that writes those two roles. After it, the owner drags them above the bot's role and `stand-down` and `session-check` close the session.
- `/ticket`, a private form that posts into a staff `tickets` forum through a worker secret. `/issue show` and `/issue new` replace `/issue` and `/bug`. The commands `bug` and the old `/issue` are removed by the next `apply`, so type the new names. A ticket's limit is kept per running copy of the worker and is given back only when Discord certainly refused the post.
- New channels: `private-help`, a staff `tickets` forum, a staff voice channel, `ci-alerts`, a `docs` channel with pinned links and the Ideas and Research forums in Community. Every channel and category is created on the first apply. A pinned Read first post in each public forum, edited in place and found again when it is archived or retitled.
- The relay gives a good first issue its own lead, names each discussion category in words, posts Ideas and Research discussions as forum posts that carry a tag and alerts staff to a failed run on the default branch.
- Managed messages can be posted as embeds with the brand's colour, the organisation's mark and a banner on the first message, set for each channel with `style`, `banner` and `pin`. The banner's tagline is also written in the embed and every image carries alt text. The images are uploaded as attachments and kept in `assets/`.
- Links by id: `{channel:x}`, `{role:x}` and `{command:x}` become clickable mentions and never ping. Commands are registered before the messages are written, so one `apply` is enough.
- Pins for managed messages, in order, with the notice each pin leaves removed. Managed messages are found through the pin list and by paging back, so a busy channel does not make them post again. This needs the Pin Messages permission, so the bot must be authorised again.
- Town hall can be run by Maintainer and Moderator: they hold Manage Channels, Mute Members and Move Members on that stage only. The bot holds Mute Members, Move Members and Request to Speak so it can grant them, which is one more authorisation.
- A `welcome` channel, first in Start here and read-only, as the system channel, so Discord's own join message announces each member there. `system_channel_flags` is 6: boost notices and setup tips off, join messages and the wave reply on.
- A `bot-commands` channel in Community with a pinned message that lists every member command as a link, built from `content/commands.toml`. `/help` points to it and `start-here` mentions it.
- A refused request now prints Discord's own field paths, codes and messages, with ids and tokens masked. `check` refuses onboarding defaults and options Discord would refuse and auto moderation patterns it cannot take. A role tied with the bot's own role is an owner step.
- `serverkit rules-text` prints the rules as plain text for Rules Screening.
- `serverkit`, a script that builds the server from a layout file. It plans first, finds everything by name, never holds Administrator and writes an audit log reason on every change.
- A layout file, the member-facing texts and a fake Discord API with tests.
- Auto moderation, onboarding, forums, webhooks and slash command registration in one run.

### Changed

- The roles the script creates are placed directly below the bot's role in one request. A role that was already there and any role the script did not create, keeps its place. A pointer at a channel the bot cannot see is an owner step. A failed or skipped step also skips the steps that depend on it.
- The server is described in one TOML file for each project in place of constants in a script.
- The bot no longer needs the Server Members or Message Content intents and two third-party bots are no longer needed.

### Removed

- `setup_discord.py` and its `discord.py` requirement.
