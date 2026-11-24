"""Reads the server as it is now. Nothing here writes."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field

from serverkit.http import ApiError, Client

TEXT, VOICE, CATEGORY, ANNOUNCEMENT, STAGE, FORUM = 0, 2, 4, 5, 13, 15
CONVERTIBLE = {TEXT, ANNOUNCEMENT}
SUPPRESS_EMBEDS = 4
REQUIRE_TAG = 1 << 4


class SetupError(Exception):
    """The run cannot start. Exit code 2."""


def norm_channel(name: str) -> str:
    """Discord lower cases a channel name and swaps spaces for hyphens."""
    return name.strip().lower().replace(" ", "-")


@dataclass
class Snapshot:
    me: dict
    app: dict
    guild: dict
    roles: list[dict]
    channels: list[dict]
    automod: list[dict]
    onboarding: dict | None
    webhooks: list[dict]
    commands: list[dict]
    member_count: int | None
    bot_role: dict | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def guild_id(self) -> str:
        return self.guild["id"]

    @property
    def features(self) -> set[str]:
        return set(self.guild.get("features", []))

    @property
    def community(self) -> bool:
        return "COMMUNITY" in self.features

    def role_by_id(self, role_id: str) -> dict | None:
        return next((r for r in self.roles if r["id"] == role_id), None)

    def channel_by_id(self, channel_id: str) -> dict | None:
        return next((c for c in self.channels if c["id"] == channel_id), None)


def find_guild(client: Client, name: str, guild_id: str | None) -> dict:
    guilds = client.request("GET", "/users/@me/guilds")
    if guild_id:
        match = [g for g in guilds if g["id"] == guild_id and g["name"] == name]
        if not match:
            raise SetupError(f'the server named by DISCORD_GUILD_ID is not called "{name}" or the bot is not in it')
        return match[0]
    match = [g for g in guilds if g["name"] == name]
    if not match:
        seen = ", ".join(f'"{g["name"]}"' for g in guilds) or "none"
        raise SetupError(f'the bot is not in a server called "{name}". It can see: {seen}')
    if len(match) > 1:
        raise SetupError(f'two servers are called "{name}". Set DISCORD_GUILD_ID to pick one')
    return match[0]


def load_snapshot(client: Client, server_name: str, guild_id: str | None) -> Snapshot:
    me = client.request("GET", "/users/@me")
    app = client.request("GET", "/applications/@me")
    guild_ref = find_guild(client, server_name, guild_id)
    gid = guild_ref["id"]
    try:
        guild = client.request("GET", f"/guilds/{gid}?with_counts=true")
    except ApiError as err:
        if err.status == 404:
            raise SetupError("the bot cannot open that server. Check DISCORD_GUILD_ID") from None
        raise
    roles = client.request("GET", f"/guilds/{gid}/roles")
    channels = client.request("GET", f"/guilds/{gid}/channels")
    automod = client.request("GET", f"/guilds/{gid}/auto-moderation/rules")
    notes: list[str] = []
    try:
        onboarding = client.request("GET", f"/guilds/{gid}/onboarding")
    except ApiError as err:
        if err.status not in (403, 404):
            raise
        onboarding = None
        notes.append("onboarding could not be read")
    webhooks = client.request("GET", f"/guilds/{gid}/webhooks")
    commands = client.request("GET", f"/applications/{app['id']}/guilds/{gid}/commands")
    snap = Snapshot(
        me=me,
        app=app,
        guild=guild,
        roles=roles,
        channels=channels,
        automod=automod,
        onboarding=onboarding,
        webhooks=webhooks,
        commands=commands,
        member_count=guild.get("approximate_member_count"),
        notes=notes,
    )
    snap.bot_role = next(
        (r for r in roles if (r.get("tags") or {}).get("bot_id") == me["id"]),
        None,
    )
    return snap


PAGE_BACK_LIMIT = 40  # pages of 100 messages read back when the managed messages are not in the latest page


def pinned_messages(client: Client, channel_id: str) -> list[dict]:
    """The pinned messages of a channel, in the order the API lists them."""
    found: list[dict] = []
    before = None
    while True:
        path = f"/channels/{channel_id}/messages/pins?limit=50" + (f"&before={before}" if before else "")
        page = client.request("GET", path)
        items = page.get("items", [])
        found += [item["message"] for item in items]
        if not page.get("has_more") or not items:
            return found
        before = items[-1]["pinned_at"]


def bot_messages(client: Client, channel_id: str, bot_id: str, want: int = 0) -> list[dict]:
    """The bot's own messages in a channel, oldest first.

    A channel where members talk soon pushes the managed messages out of the latest 100, so the pin list is read
    as well. When `want` messages are still not found the channel is read further back, a page at a time.
    """
    # type 0 is an ordinary message. The "pinned a message" notice the bot leaves is type 6 and is not ours to manage
    found: dict[str, dict] = {}

    def take(messages: list[dict]) -> None:
        for m in messages:
            if m["author"]["id"] == bot_id and m.get("type", 0) == 0:
                found[m["id"]] = m

    page = client.request("GET", f"/channels/{channel_id}/messages?limit=100")
    take(page)
    # the pin list is a second way in. The caller that needs the pins asks for them and reports a refusal
    with contextlib.suppress(ApiError):
        take(pinned_messages(client, channel_id))
    pages = 1
    while len(found) < want and len(page) == 100 and pages < PAGE_BACK_LIMIT:
        oldest = min(page, key=lambda m: (len(m["id"]), m["id"]))["id"]
        page = client.request("GET", f"/channels/{channel_id}/messages?limit=100&before={oldest}")
        take(page)
        pages += 1
    return sorted(found.values(), key=lambda m: (len(m["id"]), m["id"]))


TEXT_LIKE = (TEXT, ANNOUNCEMENT, FORUM)


def text_channel(channels: list[dict], name: str) -> dict | None:
    """A channel that holds messages, found by name. A voice channel of the same name is not one."""
    return next((c for c in channels if c["name"] == name and c["type"] in TEXT_LIKE), None)
