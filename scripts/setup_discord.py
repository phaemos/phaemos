from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass

import discord

REASON = "PHAEMOS server setup (scripts/setup_discord.py)"
EVERYONE = "@everyone"
# Discord rejects messages over 2,000 characters, so a longer summary is split by line.
MESSAGE_LIMIT = 2000


@dataclass(frozen=True)
class RoleSpec:
    name: str
    permissions: discord.Permissions
    colour: discord.Colour
    hoist: bool


@dataclass(frozen=True)
class CategorySpec:
    name: str
    channels: tuple[str, ...]
    # role name (or @everyone) -> the permission flags to allow (True) or deny (False)
    overwrites: dict[str, dict[str, bool]]


@dataclass(frozen=True)
class ThirdPartyBot:
    name: str
    # for these bots the user id is the same as the application id
    app_id: int
    permissions: discord.Permissions
    dashboard: str
    setup: str


MEMBER_PERMISSIONS = discord.Permissions(
    view_channel=True,
    send_messages=True,
    send_messages_in_threads=True,
    create_public_threads=True,
    read_message_history=True,
    embed_links=True,
    attach_files=True,
    add_reactions=True,
    use_external_emojis=True,
    change_nickname=True,
    connect=True,
    speak=True,
)

# listed highest first. Discord adds a new role just above @everyone, so creating them in this
# order on a fresh server leaves Admin at the top of the list.
ROLES = (
    RoleSpec("Admin", discord.Permissions(administrator=True), discord.Colour.red(), hoist=True),
    RoleSpec(
        "Maintainer",
        MEMBER_PERMISSIONS
        | discord.Permissions(
            manage_messages=True,
            pin_messages=True,
            create_private_threads=True,
            manage_threads=True,
        ),
        discord.Colour.blue(),
        hoist=True,
    ),
    # marks someone with a merged pull request or an accepted issue, so it carries no extra rights
    RoleSpec("Contributor", discord.Permissions.none(), discord.Colour.green(), hoist=True),
    RoleSpec("Member", MEMBER_PERMISSIONS, discord.Colour.default(), hoist=False),
    RoleSpec("Bot", discord.Permissions.none(), discord.Colour.dark_grey(), hoist=False),
)

STAFF_POST = {
    EVERYONE: {"send_messages": False, "create_public_threads": False},
    "Admin": {"send_messages": True},
    "Maintainer": {"send_messages": True},
}
# bots post their logs in #bot-logs, so the Bot role sees the hidden category too. No person holds it.
STAFF_ONLY = {
    EVERYONE: {"view_channel": False},
    "Admin": {"view_channel": True},
    "Maintainer": {"view_channel": True},
    "Bot": {"view_channel": True},
}

CATEGORIES = (
    CategorySpec("PHAEMOS", ("announcements", "general", "releases"), {}),
    CategorySpec("Support", ("help", "bugs", "feature-requests"), {}),
    CategorySpec("Hardware", ("esp32", "stm32", "arduino-nano", "pico-w"), {}),
    CategorySpec("Community", ("show-and-tell", "ideas"), {}),
    CategorySpec("Admin", ("bot-logs", "moderation"), STAFF_ONLY),
)
CHANNEL_OVERWRITES = {"announcements": STAFF_POST}

THIRD_PARTY_BOTS = (
    ThirdPartyBot(
        "Ticket Tool",
        557628352828014614,
        # opens a private channel per ticket, so it needs to manage channels and their permissions
        discord.Permissions(
            view_channel=True,
            manage_channels=True,
            manage_roles=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
            read_message_history=True,
            manage_messages=True,
            add_reactions=True,
        ),
        "https://tickettool.xyz",
        "open a ticket panel in #help and another in #bugs, with Admin and Maintainer as the support roles",
    ),
    ThirdPartyBot(
        "Carl-bot",
        235148962103951360,
        # the welcome message and the default role only
        discord.Permissions(
            view_channel=True,
            manage_roles=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
            read_message_history=True,
        ),
        "https://carl.gg",
        "turn on the welcome message in #general and an autorole that gives Member to everyone who joins",
    ),
)


def _find(items, name: str):
    return discord.utils.find(lambda item: item.name.lower() == name.lower(), items)


async def ensure_roles(guild: discord.Guild, changes: list[str]) -> dict[str, discord.Role]:
    roles = {}
    for spec in ROLES:
        # skip managed roles, which Discord creates for each bot and nobody can edit
        role = _find([r for r in guild.roles if not r.managed], spec.name)
        if role is None:
            role = await guild.create_role(
                name=spec.name, permissions=spec.permissions, colour=spec.colour, hoist=spec.hoist, reason=REASON
            )
            changes.append(f"created role {spec.name}")
        elif (role.permissions, role.colour, role.hoist) != (spec.permissions, spec.colour, spec.hoist):
            await role.edit(permissions=spec.permissions, colour=spec.colour, hoist=spec.hoist, reason=REASON)
            changes.append(f"updated role {spec.name}")
        roles[spec.name] = role
    return roles


def _resolve(guild: discord.Guild, roles: dict[str, discord.Role], spec: dict[str, dict[str, bool]]):
    return {(guild.default_role if name == EVERYONE else roles[name]): flags for name, flags in spec.items()}


async def ensure_overwrites(target, wanted: dict, label: str, changes: list[str]) -> None:
    # only the flags named here are enforced, so permissions added by hand on top survive a rerun
    for who, flags in wanted.items():
        current = target.overwrites_for(who)
        if any(getattr(current, flag) is not value for flag, value in flags.items()):
            current.update(**flags)
            await target.set_permissions(who, overwrite=current, reason=REASON)
            changes.append(f"set {who.name} permissions on {label}")


async def ensure_channels(guild: discord.Guild, roles: dict[str, discord.Role], changes: list[str]):
    categories, channels = {}, {}
    for spec in CATEGORIES:
        category_overwrites = _resolve(guild, roles, spec.overwrites)
        category = _find(guild.categories, spec.name)
        if category is None:
            category = await guild.create_category(
                spec.name,
                overwrites={who: discord.PermissionOverwrite(**flags) for who, flags in category_overwrites.items()},
                reason=REASON,
            )
            changes.append(f"created category {spec.name}")
        else:
            await ensure_overwrites(category, category_overwrites, f"category {spec.name}", changes)
        categories[spec.name] = category

        for name in spec.channels:
            # a channel carries its category's rules as well as its own, so it stays hidden or
            # read-only even if someone breaks its sync with the category
            wanted = {**category_overwrites}
            for who, flags in _resolve(guild, roles, CHANNEL_OVERWRITES.get(name, {})).items():
                wanted[who] = {**wanted.get(who, {}), **flags}
            channel = _find(guild.text_channels, name)
            if channel is None:
                channel = await guild.create_text_channel(
                    name,
                    category=category,
                    overwrites={who: discord.PermissionOverwrite(**flags) for who, flags in wanted.items()},
                    reason=REASON,
                )
                changes.append(f"created #{name}")
            else:
                if channel.category != category:
                    await channel.edit(category=category, reason=REASON)
                    changes.append(f"moved #{name} to {spec.name}")
                await ensure_overwrites(channel, wanted, f"#{name}", changes)
            channels[name] = channel
    return categories, channels


async def ensure_bot_role(guild: discord.Guild, bot_role: discord.Role, changes: list[str]) -> None:
    for member in guild.members:
        if member.bot and bot_role not in member.roles:
            await member.add_roles(bot_role, reason=REASON)
            changes.append(f"gave the Bot role to {member.name}")


def build_summary(guild: discord.Guild, roles: dict, categories: dict, channels: dict) -> str:
    lines = ["**PHAEMOS server setup**", "", "**Roles**"]
    lines += [f"- {role.name} `{role.id}`" for role in roles.values()]
    lines += ["", "**Channels**"]
    for spec in CATEGORIES:
        lines.append(f"- {spec.name} `{categories[spec.name].id}`")
        lines += [f"  - #{name} `{channels[name].id}`" for name in spec.channels]
    lines += ["", "**Bot invites**"]
    for bot in THIRD_PARTY_BOTS:
        url = discord.utils.oauth_url(
            bot.app_id, permissions=bot.permissions, guild=guild, scopes=("bot", "applications.commands")
        )
        lines.append(f"- {bot.name}: <{url}>")

    todo = []
    for bot in THIRD_PARTY_BOTS:
        if guild.get_member(bot.app_id) is None:
            todo.append(f"Invite {bot.name} with the link above, then run this script again so it gets the Bot role.")
        todo.append(f"In the {bot.name} dashboard (<{bot.dashboard}>), {bot.setup}.")
    todo += [
        "Give Contributor to anyone with a merged pull request or an accepted issue.",
        "Narrow this bot's Administrator permission to Manage Roles, Manage Channels, View Channels, "
        "Send Messages and Read Message History. A bot can only grant permissions it has, so give "
        "Administrator back before a rerun that has to repair a role or a channel's permissions.",
    ]
    lines += ["", "**Left to do by hand**"]
    lines += [f"{n}. {step}" for n, step in enumerate(todo, start=1)]
    return "\n".join(lines)


def _chunks(text: str) -> list[str]:
    chunks, current = [], ""
    for line in text.split("\n"):
        if current and len(current) + 1 + len(line) > MESSAGE_LIMIT:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    # Discord trims the whitespace around a message, so trim here too or a rerun would never match
    return [chunk.strip() for chunk in chunks + [current] if chunk.strip()]


async def post_summary(channel: discord.TextChannel, me: discord.abc.User, text: str, changes: list[str]) -> None:
    chunks = _chunks(text)
    # history comes newest first. If the last summary this bot posted is the same, posting it again
    # would be the only change, so a rerun on a finished server leaves #bot-logs alone.
    own = [m async for m in channel.history(limit=50) if m.author.id == me.id]
    if [m.content for m in reversed(own[: len(chunks)])] == chunks:
        return
    for chunk in chunks:
        await channel.send(chunk, allowed_mentions=discord.AllowedMentions.none())
    changes.append("posted the summary to #bot-logs")


async def setup_server(guild: discord.Guild, me: discord.abc.User) -> list[str]:
    changes: list[str] = []
    roles = await ensure_roles(guild, changes)
    categories, channels = await ensure_channels(guild, roles, changes)
    await ensure_bot_role(guild, roles["Bot"], changes)
    await post_summary(channels["bot-logs"], me, build_summary(guild, roles, categories, channels), changes)
    return changes


class SetupClient(discord.Client):
    def __init__(self, guild_id: int) -> None:
        intents = discord.Intents.default()
        # the member list is how the script finds every bot account to give the Bot role
        intents.members = True
        super().__init__(intents=intents)
        self.guild_id = guild_id
        self.changes: list[str] = []
        self.error: BaseException | None = None
        self._started = False

    async def on_ready(self) -> None:
        # on_ready fires again after a reconnect, and the setup must only run once
        if self._started:
            return
        self._started = True
        try:
            guild = self.get_guild(self.guild_id)
            if guild is None:
                raise SystemExit(f"The bot is not in server {self.guild_id}. Invite it first, then run this again.")
            self.changes = await setup_server(guild, self.user)
        except BaseException as exc:
            # discord.py logs and swallows errors raised in events, so keep it to raise after closing
            self.error = exc
        finally:
            await self.close()


async def main() -> int:
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    guild_id = os.environ.get("DISCORD_GUILD_ID", "").strip()
    if not token or not guild_id.isdigit():
        print("Set DISCORD_BOT_TOKEN and DISCORD_GUILD_ID (the numeric server id) first.", file=sys.stderr)
        return 2

    client = SetupClient(int(guild_id))
    try:
        async with client:
            await client.start(token)
    except discord.LoginFailure:
        print("Discord refused DISCORD_BOT_TOKEN. Copy the token again from the developer portal.", file=sys.stderr)
        return 1
    except discord.PrivilegedIntentsRequired:
        print("Turn on the Server Members intent in the bot settings of the developer portal.", file=sys.stderr)
        return 1
    if client.error is not None:
        raise client.error

    for change in client.changes:
        print(f"- {change}")
    print(f"{len(client.changes)} changes." if client.changes else "No changes: the server already matches.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
