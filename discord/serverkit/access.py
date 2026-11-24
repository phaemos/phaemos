"""What each kind of account can do in each channel, worked out from the layout alone.

The same arithmetic Discord documents is applied to the layout, so a change that would lock the owner
out, hide the rules or show a staff channel fails `check` before anything is sent.
"""

from __future__ import annotations

from dataclasses import dataclass

from serverkit import perms
from serverkit.layout import Channel, Layout

STAFF_ROLES = ("Maintainer", "Moderator")
NEW_ARRIVAL = "new arrival"
MEMBER = "member"
BOT = "bot"
# a new arrival who has not passed Discord's gates can read and nothing else
ARRIVAL_MASK = perms.BIT["view_channel"] | perms.BIT["read_message_history"]


@dataclass(frozen=True)
class Access:
    value: int

    def has(self, name: str) -> bool:
        return bool(self.value & perms.BIT[name])

    @property
    def visible(self) -> bool:
        return self.has("view_channel")

    @property
    def reads(self) -> bool:
        return self.has("view_channel") and self.has("read_message_history")

    @property
    def posts(self) -> bool:
        return self.has("view_channel") and self.has("send_messages")

    @property
    def reacts(self) -> bool:
        return self.has("view_channel") and self.has("add_reactions")

    @property
    def replies_in_threads(self) -> bool:
        return self.has("view_channel") and self.has("send_messages_in_threads")

    @property
    def deletes(self) -> bool:
        return self.has("view_channel") and self.has("manage_messages")

    @property
    def pins(self) -> bool:
        return self.has("view_channel") and self.has("pin_messages")

    @property
    def connects(self) -> bool:
        return self.has("view_channel") and self.has("connect")

    @property
    def speaks(self) -> bool:
        return self.has("view_channel") and self.has("connect") and self.has("speak")

    @property
    def requests_to_speak(self) -> bool:
        return self.has("view_channel") and self.has("connect") and self.has("request_to_speak")

    @property
    def manages_channel(self) -> bool:
        return self.has("manage_channels")

    @property
    def manages_threads(self) -> bool:
        return self.has("view_channel") and self.has("manage_threads")


def holders(layout: Layout) -> dict[str, list[str]]:
    """The kinds of account to check: the roles each one holds."""
    kinds = {NEW_ARRIVAL: [], MEMBER: [], BOT: []}
    for role in layout.roles:
        kinds[role.name] = [role.name]
    return kinds


def access_in(layout: Layout, kind: str, roles: list[str], channel: Channel) -> Access:
    rows = {o.target: (o.allow, o.deny) for o in channel.overwrites}
    if kind == BOT:
        base = perms.base_permissions(layout.everyone, [layout.bot_permissions(waiting=True)])
        role_rows = [rows["@bot"]] if "@bot" in rows else []
    else:
        by_name = {r.name: r.permissions for r in layout.roles}
        base = perms.base_permissions(layout.everyone, [by_name[n] for n in roles])
        role_rows = [rows[n] for n in roles if n in rows]
    value = perms.channel_permissions(base, rows.get("@everyone"), role_rows, voice=channel.type in ("voice", "stage"))
    if kind == NEW_ARRIVAL:
        value &= ARRIVAL_MASK
    return Access(value)


def table(layout: Layout) -> dict[str, dict[str, Access]]:
    """For each kind of account and each active channel, what it holds there."""
    result: dict[str, dict[str, Access]] = {}
    for kind, roles in holders(layout).items():
        result[kind] = {c.name: access_in(layout, kind, roles, c) for c in layout.active_channels}
    return result


def access_problems(layout: Layout) -> list[str]:
    problems: list[str] = []
    grid = table(layout)
    rules = layout.server.get("rules_channel")
    for kind in (NEW_ARRIVAL, MEMBER):
        if rules and not grid[kind][rules].reads:
            problems.append(f"a {kind} cannot read the rules channel {rules}")
    # join messages are written into the system channel by Discord, so nobody else may write there
    system = layout.server.get("system_channel")
    if system and layout.channel(system) and layout.channel_active(layout.channel(system)):
        for kind in holders(layout):
            if kind not in (BOT, *STAFF_ROLES) and grid[kind][system].posts:
                problems.append(
                    f"the system channel {system} lets {kind} send messages, so it would not stay a list of joins"
                )
        if not grid[MEMBER][system].reads:
            problems.append(f"a {MEMBER} cannot read the system channel {system}")
    for kind in holders(layout):
        if kind in (NEW_ARRIVAL, MEMBER, BOT):
            continue
        if rules and not grid[kind][rules].reads:
            problems.append(f"the {kind} role cannot read the rules channel {rules}")
    for channel in layout.active_channels:
        if channel.staff:
            for kind in holders(layout):
                visible = grid[kind][channel.name].visible
                should = kind in (*STAFF_ROLES, BOT)
                if visible and not should:
                    problems.append(f"the staff channel {channel.name} is visible to {kind}")
                if should and not visible:
                    problems.append(
                        f"the staff channel {channel.name} is hidden from {kind}, which would lock staff out"
                    )
    # the bot must be able to see and write where it has to
    for channel in layout.active_channels:
        bot = grid[BOT][channel.name]
        if not bot.visible:
            problems.append(f"the bot cannot see {channel.name}")
    problems += bot_row_problems(layout)
    for channel in layout.active_channels:
        if not grid[BOT][channel.name].manages_channel:
            problems.append(f"the bot could not manage {channel.name}, which would lock it out of its own work")
    # a voice or stage channel waits, but the day it is switched on members must be able to join it and the
    # bot must still manage it (denying Connect also takes Manage Channels away)
    for channel in layout.channels:
        if channel.type not in ("voice", "stage"):
            continue
        # a staff voice channel is for staff, so it is staff who must be able to join and speak there
        who, roles = ("Maintainer", ["Maintainer"]) if channel.staff else (MEMBER, [])
        user = access_in(layout, who, roles, channel)
        bot = access_in(layout, BOT, [], channel)
        if channel.type == "voice" and not user.speaks:
            problems.append(f"{who} could not connect and speak in the voice channel {channel.name}")
        if channel.type == "stage" and not user.requests_to_speak:
            problems.append(f"{who} could not join and ask to speak in the stage channel {channel.name}")
        if not bot.manages_channel:
            problems.append(f"the bot could not manage the {channel.type} channel {channel.name}")
    summary = layout.server.get("summary_channel")
    for name in (rules, "start-here", summary):
        if name and layout.channel(name) and layout.channel_active(layout.channel(name)) and not grid[BOT][name].posts:
            problems.append(f"the bot cannot post in {name}")
    return problems


def bot_row_problems(layout: Layout) -> list[str]:
    """Fails a layout that would ask the bot to allow or deny what it does not hold where it writes.

    From the channel pages: "Only permissions your bot has in the guild or parent channel (if applicable) can
    be allowed/denied". For a channel in a category that means the bot's permissions in the category.
    """
    problems = []
    held = layout.bot_permissions(waiting=True)
    base = perms.base_permissions(layout.everyone, [held])
    for category in layout.categories:
        if not category.enabled:
            continue
        named = 0
        for o in category.overwrites:
            named |= o.allow | o.deny
        if named & ~base:
            problems.append(f"the category {category.name} names a permission the bot does not hold in the server")
    for channel in layout.active_channels:
        named = 0
        for o in channel.overwrites:
            named |= o.allow | o.deny
        if channel.category:
            category = layout.category(channel.category)
            rows = {o.target: (o.allow, o.deny) for o in category.overwrites}
            where = perms.channel_permissions(base, rows.get("@everyone"), [rows["@bot"]] if "@bot" in rows else [])
            place = f"the category {channel.category}"
        else:
            where = base
            place = "the server"
        if named & ~where:
            missing = ", ".join(perms.names_of(named & ~where))
            problems.append(
                f"the bot would be asked to allow or deny {missing} in {channel.name} but does not hold it in {place}"
            )
    return problems
