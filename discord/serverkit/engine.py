"""Works out what differs between the layout and the server, then makes the changes.

Every step reads first and writes only what differs. A change is a line of the plan and, when it can be
applied, a function that sends it. Names are matched at run time and no id is ever written down.
"""

from __future__ import annotations

import hashlib
import itertools
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from serverkit import commandset, perms, textfmt
from serverkit.http import ApiError, Client
from serverkit.layout import (
    ACTIONS,
    FORUM_LAYOUT,
    FORUM_SORT,
    ONBOARDING_MODES,
    PRESETS,
    PROMPT_TYPES,
    TRIGGERS,
    Channel,
    Layout,
    Overwrite,
    contact_email,
    read_first_text,
)
from serverkit.state import (
    CONVERTIBLE,
    REQUIRE_TAG,
    SUPPRESS_EMBEDS,
    SetupError,
    Snapshot,
    bot_messages,
    norm_channel,
    pinned_messages,
)

STEPS = (
    "settings",
    "roles",
    "channels",
    "pointers",
    "automod",
    "onboarding",
    "commands",
    "messages",
    "readfirst",
    "pins",
    "webhooks",
    "application",
)
SECTIONS = {
    "settings": "Server settings",
    "pointers": "Server settings",
    "roles": "Roles",
    "channels": "Channels",
    "automod": "Auto moderation",
    "onboarding": "Onboarding",
    "messages": "Messages",
    "pins": "Pins",
    "readfirst": "Read first posts",
    "webhooks": "Webhooks",
    "commands": "Commands",
    "application": "Application",
}
PRUNE_KINDS = ("channels", "roles", "overwrites", "automod", "webhooks", "messages", "commands")
VERIFICATION = ["none", "low", "medium", "high", "very high"]
NOTIFICATIONS = ["all messages", "only mentions"]
CONTENT_FILTER = ["off", "members without roles", "all members"]
ANNOUNCEMENT_NEEDS = "needs Community"
LOCKOUT_NEEDS = ("view_channel", "manage_channels", "manage_roles")


class Blocked(Exception):
    """A change that cannot be made until the owner acts by hand."""


class Lockout(Exception):
    """A write that would leave the bot unable to see or manage a channel."""


@dataclass
class Change:
    step: str
    word: str
    text: str
    run: Callable[[], None] | None = None
    destructive: bool = False
    held: bool = False
    owner_step: str = ""
    follows: Change | None = None


@dataclass
class Options:
    allow_renames: bool = False
    prune: str | None = None
    rotate: list[str] = field(default_factory=list)
    only: set[str] | None = None
    summary: bool = True
    interactions_url: str | None = None


def q(name: str) -> str:
    return f'"{name}"'


def perm_text(old: int, new: int) -> str:
    parts = []
    for label, names in (("remove", perms.names_of(old & ~new)), ("add", perms.names_of(new & ~old))):
        if not names:
            continue
        if len(names) <= 3:
            shown = ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0]
        else:
            shown = f"{', '.join(names[:2])} and {len(names) - 2} more"
        parts.append(f"{label} {shown}")
    return ", ".join(parts) if parts else "no change"


class Ctx:
    """Everything a run knows: the layout, the server as read and the ids found or created."""

    def __init__(self, layout: Layout, snap: Snapshot, client: Client, opts: Options):
        self.layout = layout
        self.snap = snap
        self.client = client
        self.opts = opts
        self.problems: list[str] = []
        self.role_ids: dict[str, str] = {}
        self.channel_ids: dict[str, str] = {}
        self.category_ids: dict[str, str] = {}
        self.applied: list[Change] = []
        # channels that will not exist after this run, so what depends on them waits
        self.unavailable: set[str] = set()
        # commands by name for {command:x} links and the ones this run registers
        self.command_ids: dict[str, str] = {
            c["name"].lower(): c["id"] for c in snap.commands if c.get("type", 1) == 1 and c.get("id")
        }
        self.planned_commands: set[str] = set()

    # ids ---------------------------------------------------------------------------------------

    @property
    def gid(self) -> str:
        return self.snap.guild_id

    @property
    def bot_id(self) -> str:
        return self.snap.me["id"]

    @property
    def bot_role_id(self) -> str | None:
        return self.snap.bot_role["id"] if self.snap.bot_role else None

    def rid(self, name: str) -> str | None:
        return self.role_ids.get(name.lower())

    def cid(self, name: str) -> str | None:
        return self.channel_ids.get(name)

    def target_id(self, target: str) -> str | None:
        if target == "@everyone":
            return self.gid
        if target == "@bot":
            return self.bot_role_id
        return self.rid(target)

    def reason(self, what: str) -> str:
        return f"{self.layout.name} layout {self.layout.hash8}: {what}"

    def write(self, method: str, path: str, body, what: str, recheck=None, files=None):
        return self.client.request(method, path, body, reason=self.reason(what), recheck=recheck, files=files)

    # names for output --------------------------------------------------------------------------

    def role_label(self, role_id: str) -> str:
        role = self.snap.role_by_id(role_id)
        return f"role {q(role['name'])}" if role else "a member"


def upsert(items: list[dict], obj: dict) -> None:
    for index, item in enumerate(items):
        if item["id"] == obj["id"]:
            items[index] = {**item, **obj}
            return
    items.append(obj)


# ----------------------------------------------------------------------------------------------
# overwrites


def overwrite_payload(ctx: Ctx, wanted: list[Overwrite]) -> list[dict] | None:
    """The wanted rows with ids or None while a role they name does not exist yet."""
    rows = []
    for o in wanted:
        target = ctx.target_id(o.target)
        if target is None:
            return None
        rows.append({"id": target, "type": 0, "allow": str(o.allow), "deny": str(o.deny)})
    return rows


def keep_unmanaged(ctx: Ctx, existing: list[dict], rows: list[dict]) -> list[dict]:
    """Rows for targets the layout does not name stay as they are. Only --prune overwrites drops them."""
    named = {row["id"] for row in rows}
    if ctx.opts.prune == "overwrites":
        return rows
    return rows + [
        {"id": o["id"], "type": o["type"], "allow": str(o["allow"]), "deny": str(o["deny"])}
        for o in existing
        if o["id"] not in named
    ]


def overwrites_differ(existing: list[dict], rows: list[dict] | None) -> bool:
    if rows is None:
        return True
    have = {o["id"]: (int(o["allow"]), int(o["deny"])) for o in existing}
    return any(have.get(r["id"]) != (int(r["allow"]), int(r["deny"])) for r in rows)


def bot_effective(ctx: Ctx, rows: list[dict]) -> int:
    """What the bot would hold in a channel with these rows, by the documented order."""
    everyone = ctx.snap.role_by_id(ctx.gid)
    base = int(everyone["permissions"]) if everyone else 0
    bot_role = ctx.snap.bot_role
    if bot_role:
        base |= int(bot_role["permissions"])
    if base & perms.BIT["administrator"]:
        return perms.ALL_PERMISSIONS
    everyone_ow = None
    role_ows = []
    member_ow = None
    for row in rows:
        pair = (int(row["allow"]), int(row["deny"]))
        if row["id"] == ctx.gid:
            everyone_ow = pair
        elif row["id"] == ctx.bot_role_id:
            role_ows.append(pair)
        elif row["id"] == ctx.bot_id and row["type"] == 1:
            member_ow = pair
    value = perms.channel_permissions(base, everyone_ow, role_ows)
    if member_ow:
        value = perms.apply_implicit((value & ~member_ow[1]) | member_ow[0])
    return value


def lockout_check(ctx: Ctx, label: str, rows: list[dict]) -> None:
    if not ctx.snap.bot_role:
        return
    value = bot_effective(ctx, rows)
    missing = [n for n in LOCKOUT_NEEDS if not value & perms.BIT[n]]
    if missing:
        raise Lockout(
            f"stopped before writing {label}: the bot would be left without {', '.join(missing)} there. "
            "Nothing was sent for it"
        )


# ----------------------------------------------------------------------------------------------
# step 2: server settings


def plan_settings(ctx: Ctx) -> list[Change]:
    s = ctx.layout.server
    guild = ctx.snap.guild
    wanted = {
        "verification_level": s["verification_level"],
        "explicit_content_filter": s["explicit_content_filter"],
        "default_message_notifications": s["default_message_notifications"],
        "preferred_locale": s["preferred_locale"],
        "description": s["description"],
        "system_channel_flags": s.get("system_channel_flags", 0),
    }
    labels = {
        "verification_level": ("verification level", lambda v: VERIFICATION[v]),
        "explicit_content_filter": ("media filter", lambda v: CONTENT_FILTER[v]),
        "default_message_notifications": ("default notifications", lambda v: NOTIFICATIONS[v]),
        "preferred_locale": ("preferred language", str),
        "description": ("description", lambda v: "set" if v else "empty"),
        "system_channel_flags": ("system message flags", str),
    }
    changes = []
    for key, value in wanted.items():
        current = guild.get(key)
        if key == "description":
            current = current or ""
        if current == value:
            continue
        name, show = labels[key]
        before = "none" if current is None else show(current)
        changes.append((key, value, f"{name}: {before} -> {show(value)}"))

    out = []
    for key, value, text in changes:

        def run(key=key, value=value, text=text):
            ctx.write("PATCH", f"/guilds/{ctx.gid}", {key: value}, f"set {text.split(':')[0]}")
            ctx.snap.guild[key] = value

        out.append(Change("settings", "update", text, run))
    return out


# ----------------------------------------------------------------------------------------------
# step 3: roles


def match_role(ctx: Ctx, name: str) -> dict | None:
    found = [
        r for r in ctx.snap.roles if not r.get("managed") and r["name"].lower() == name.lower() and r["id"] != ctx.gid
    ]
    if len(found) > 1:
        ctx.problems.append(f'two roles are called "{name}". Remove one by hand')
    return found[0] if found else None


def plan_roles(ctx: Ctx) -> list[Change]:
    out: list[Change] = []
    created: list[str] = []
    layout = ctx.layout
    matched: set[str] = set()
    for role in layout.roles:
        existing = match_role(ctx, role.name)
        if role.owner:
            # an owner role is never created, edited or renamed by the script. It is read and checked
            if existing:
                ctx.role_ids[role.name.lower()] = existing["id"]
                matched.add(existing["id"])
            out.extend(check_owner_role(ctx, role, existing))
            continue
        previous = None
        if existing is None:
            for old in role.previous_names:
                previous = match_role(ctx, old)
                if previous:
                    break
        if existing:
            ctx.role_ids[role.name.lower()] = existing["id"]
            matched.add(existing["id"])
        if existing is None and previous is None:
            out.append(_create_role(ctx, role))
            created.append(role.name)
            continue
        if existing is None and previous is not None:
            matched.add(previous["id"])
            ctx.role_ids[role.name.lower()] = previous["id"]
            out.append(
                _rename(ctx, "roles", f"role {q(previous['name'])} -> {q(role.name)}", previous, role, _update_role)
            )
            continue
        out.extend(_update_role(ctx, existing, role))

    # @everyone
    everyone = ctx.snap.role_by_id(ctx.gid)
    if everyone and int(everyone["permissions"]) != layout.everyone:
        text = f"@everyone: {perm_text(int(everyone['permissions']), layout.everyone)}"

        def run_everyone(text=text):
            result = ctx.write(
                "PATCH",
                f"/guilds/{ctx.gid}/roles/{ctx.gid}",
                {"permissions": str(layout.everyone)},
                "set @everyone permissions",
            )
            upsert(ctx.snap.roles, result)

        out.append(Change("roles", "update", text, run_everyone))

    # right after the last create, so a role that was just made is placed before anything edits it
    last = max((i for i, c in enumerate(out) if c.word == "create"), default=-1)
    for offset, change in enumerate(_plan_role_order(ctx, created)):
        out.insert(last + 1 + offset, change)

    for role in ctx.snap.roles:
        if role.get("managed") or role["id"] == ctx.gid or role["id"] in matched:
            continue
        held_names = {layout_role.name.lower() for layout_role in layout.roles}
        if role["name"].lower() in held_names:
            continue
        label = q(role["name"])
        if int(role["permissions"]) & perms.BIT["administrator"]:
            out.append(Change("roles", "warning", f"role {label} holds Administrator and is not in the layout"))
        if ctx.opts.prune == "roles":
            out.append(
                _delete(
                    ctx,
                    "roles",
                    f"role {label}",
                    f"/guilds/{ctx.gid}/roles/{role['id']}",
                    f"delete role {role['name']}",
                    role,
                    ctx.snap.roles,
                )
            )
        else:
            out.append(Change("roles", "unmanaged", f"role {label} is not in the layout and is left alone"))
    return out


def _create_role(ctx: Ctx, role) -> Change:
    text = f"{role.name} ({'hoisted, ' if role.hoist else ''}{len(perms.names_of(role.permissions))} permissions)"

    def run():
        body = {
            "name": role.name,
            "permissions": str(role.permissions),
            "color": role.colour,
            "hoist": role.hoist,
            "mentionable": role.mentionable,
        }
        result = ctx.write(
            "POST",
            f"/guilds/{ctx.gid}/roles",
            body,
            f"create role {role.name}",
            recheck=lambda: _find_role(ctx, role.name),
        )
        ctx.role_ids[role.name.lower()] = result["id"]
        upsert(ctx.snap.roles, result)

    # roles that are planned but missing are named so later steps can tell
    return Change("roles", "create", text, run)


def _find_role(ctx: Ctx, name: str) -> dict | None:
    roles = ctx.client.request("GET", f"/guilds/{ctx.gid}/roles")
    return next((r for r in roles if not r.get("managed") and r["name"].lower() == name.lower()), None)


def check_owner_role(ctx: Ctx, role, existing: dict | None) -> list[Change]:
    """Compare a role the owner keeps by hand with the layout and say what to change. Nothing is written."""
    wanted = ", ".join(perms.names_of(role.permissions)) or "no permissions"
    if existing is None:
        step = (
            f'Create the {role.name} role by hand: Server Settings, Roles, Create Role. Name it exactly "{role.name}", '
            f"switch on {wanted} and switch on Display role members separately. Then drag it above the bot's role."
        )
        return [
            Change(
                "roles",
                "blocked",
                f"{role.name}: the owner makes this role by hand and it does not exist",
                owner_step=step,
            )
        ]
    held = int(existing["permissions"])
    add = perms.names_of(role.permissions & ~held)
    remove = perms.names_of(held & ~role.permissions)
    parts = []
    if add:
        parts.append(f"switch on {', '.join(add)}")
    if remove:
        parts.append(f"switch off {', '.join(remove)}")
    if bool(existing.get("hoist")) != role.hoist:
        parts.append(f"{'switch on' if role.hoist else 'switch off'} Display role members separately")
    if not parts:
        return []
    step = (
        f"Edit the {role.name} role by hand: Server Settings, Roles, {role.name}: "
        + "; ".join(parts)
        + ". The bot never edits it."
    )
    return [Change("roles", "blocked", f"{role.name}: differs from the layout ({'; '.join(parts)})", owner_step=step)]


def _update_role(ctx: Ctx, existing: dict, role, name_change: bool = False) -> list[Change]:
    diffs = []
    target = role.permissions
    check: list[Change] = []
    if int(existing["permissions"]) != target:
        diffs.append("permissions")
    if bool(existing.get("hoist")) != role.hoist:
        diffs.append("hoist")
    if bool(existing.get("mentionable")) != role.mentionable:
        diffs.append("mentionable")
    if int(existing.get("color", 0)) != role.colour:
        diffs.append("colour")
    if not diffs and not name_change:
        return check
    detail = ", ".join(diffs)
    if "permissions" in diffs:
        detail = detail.replace("permissions", f"permissions ({perm_text(int(existing['permissions']), target)})")

    def run():
        body = {
            "permissions": str(role.permissions),
            "color": role.colour,
            "hoist": role.hoist,
            "mentionable": role.mentionable,
        }
        if name_change:
            body["name"] = role.name
        result = ctx.write("PATCH", f"/guilds/{ctx.gid}/roles/{existing['id']}", body, f"update role {role.name}")
        upsert(ctx.snap.roles, result)

    return [Change("roles", "update", f"{role.name}: {detail}", run), *check]


def _bot_top(ctx: Ctx) -> int | None:
    return ctx.snap.bot_role["position"] if ctx.snap.bot_role else None


def _plan_role_order(ctx: Ctx, created: list[str]) -> list[Change]:
    """Place the roles this run creates directly below the bot's role, in layout order, in one request.

    A role made by the API lands at the bottom and can tie with the bot's own role. The documentation says only
    "roles with the same position are sorted by id", not which way, so a tie is never relied on. A role that
    already exists below the bot stays where it is and so does every role the script did not create.
    """
    top = _bot_top(ctx)
    if top is None:
        return []
    # one the script made earlier that now ties with the bot's role or sits above it cannot be moved by the bot: a bot
    # can only order roles below its own highest role. That is for the owner to drag
    names = [r.name for r in ctx.layout.roles if not r.owner]
    stuck = [
        r["name"]
        for r in ctx.snap.roles
        if r["name"] in names and not r.get("managed") and r["id"] != ctx.gid and r["position"] >= top
    ]
    out: list[Change] = []
    if stuck:
        out.append(
            Change(
                "roles",
                "blocked",
                f"role order: {', '.join(stuck)} tie with or sit above the bot's role. "
                "A bot cannot move into its own place",
                owner_step=(
                    f"In Server Settings, Roles, drag {', '.join(stuck)} below the bot's role, then run this again."
                ),
            )
        )
    created = [n for n in names if n in created]
    if created:
        out.append(
            Change(
                "roles",
                "update",
                f"role order: place {len(created)} roles directly below the bot's role",
                lambda: _apply_role_order(ctx, created),
            )
        )
    return out


def _apply_role_order(ctx: Ctx, created: list[str]) -> None:
    # creating a role ties or shifts the places of the others, so the list is read again first
    ctx.snap.roles[:] = ctx.client.request("GET", f"/guilds/{ctx.gid}/roles")
    fresh = next((r for r in ctx.snap.roles if ctx.snap.bot_role and r["id"] == ctx.snap.bot_role["id"]), None)
    ctx.snap.bot_role = fresh or ctx.snap.bot_role
    top = _bot_top(ctx)
    wanted = [r.lower() for r in created]
    mine = sorted(
        (r for r in ctx.snap.roles if r["name"].lower() in wanted and not r.get("managed") and r["id"] != ctx.gid),
        key=lambda r: wanted.index(r["name"].lower()),
    )
    if not mine or top is None:
        return
    # every place under the bot is named, so the result never depends on how Discord settles a clash. The roles
    # that were already there keep their order and go first. The new ones come last, the first in the layout
    # highest, so they end directly under the bot
    moved = {r["id"] for r in mine}
    below = sorted(
        (r for r in ctx.snap.roles if r["id"] != ctx.gid and r["position"] < top and r["id"] not in moved),
        key=lambda r: (r["position"], r["id"]),
    )
    final = [*below, *reversed(mine)]
    moves = [{"id": r["id"], "position": rank} for rank, r in enumerate(final, 1) if not r.get("managed")]
    try:
        result = ctx.write("PATCH", f"/guilds/{ctx.gid}/roles", moves, "place the new roles below the bot's role")
    except ApiError as err:
        if err.status in (400, 403):
            # a bot cannot move a role into its own place. Say so as a step for the owner and not as a failure
            raise Blocked(
                "Discord refused to order the new roles below the bot's role. In Server Settings, Roles, drag the "
                "bot's role above them, then run this again"
            ) from None
        raise
    if isinstance(result, list):
        ctx.snap.roles[:] = result
        fresh = next((r for r in result if ctx.snap.bot_role and r["id"] == ctx.snap.bot_role["id"]), None)
        ctx.snap.bot_role = fresh or ctx.snap.bot_role


# ----------------------------------------------------------------------------------------------
# helpers shared by steps


def _rename(ctx: Ctx, step: str, text: str, old: dict, new, updater) -> Change:
    held = not ctx.opts.allow_renames
    if held:
        return Change(step, "rename", f"{text}: held back, needs --allow-renames", None, held=True)
    changes = updater(ctx, old, new, True)
    run = changes[0].run if changes else None
    return Change(step, "rename", text, run, destructive=True)


def _delete(ctx: Ctx, step: str, label: str, path: str, what: str, obj: dict, collection: list[dict]) -> Change:
    def run():
        ctx.write("DELETE", path, None, what)
        collection[:] = [c for c in collection if c["id"] != obj["id"]]

    return Change(step, "delete", label, run, destructive=True)


# ----------------------------------------------------------------------------------------------
# step 4: categories and channels


def needs_community(snap: Snapshot, kind: str) -> str | None:
    """Why a channel type cannot be made yet. The one place that holds what is not certain.

    Announcement and stage channels need Community. Whether a forum does is not documented, so a forum
    is tried and a refusal is read as a block (see refusal_means_community).
    """
    if kind in ("announcement", "stage"):
        if not snap.community:
            return ANNOUNCEMENT_NEEDS
        if kind == "announcement" and "NEWS" not in snap.features:
            return "needs the NEWS feature, which Community did not switch on"
    return None


def refusal_means_community(err: ApiError, snap: Snapshot) -> bool:
    return err.status == 400 and "community" in err.message.lower() and not snap.community


def deferred_change(ctx: Ctx, step: str, label: str, obj) -> Change:
    count = ctx.snap.member_count
    need = obj.threshold_members
    if need is not None and count is not None and count >= need:
        return Change(step, "ready", f"{label}: {need} members reached, set enabled = true in the layout to create it")
    wait = obj.threshold or (f"{need} members" if need else "the owner")
    wait = wait[0].lower() + wait[1:] if wait[:2] != "50" and not wait[0].isdigit() else wait
    suffix = f", now {count}" if need is not None and count is not None else ""
    return Change(step, "deferred", f"{label}: waits for {wait}{suffix}")


def family(kind: int) -> str:
    """Text, announcement and forum channels share names. A voice or stage channel is a separate kind of place."""
    return "voice" if kind in (2, 13) else "text"


def channel_label(ch: Channel) -> str:
    return f"#{ch.name}" if ch.type in ("text", "announcement", "forum") else q(ch.name)


UNKNOWN = object()


def desired_fields(ctx: Ctx, obj, is_category: bool, existing: dict | None, partial: bool = False) -> dict | None:
    """The fields of a channel or category as they should be.

    While an id is still unknown the answer is None or with `partial` a dict that marks the unknown parts
    so the plan can still compare everything else.
    """
    rows = overwrite_payload(ctx, obj.overwrites)
    if rows is None and not partial:
        return None
    fields: dict = {"permission_overwrites": rows}
    if is_category:
        return fields
    if obj.category:
        parent = ctx.category_ids.get(obj.category.lower())
        if parent is None:
            if not partial:
                return None
            parent = UNKNOWN
        fields["parent_id"] = parent
    else:
        fields["parent_id"] = None
    if obj.type in ("text", "announcement", "forum"):
        fields["topic"] = obj.topic
    if obj.type == "forum":
        forum = obj.forum
        flags = (existing or {}).get("flags", 0) & ~REQUIRE_TAG
        fields["flags"] = flags | (REQUIRE_TAG if forum["require_tag"] else 0)
        fields["rate_limit_per_user"] = forum["post_slow_mode"]
        fields["default_thread_rate_limit_per_user"] = forum["reply_slow_mode"]
        fields["default_sort_order"] = FORUM_SORT[forum["default_sort"]]
        fields["default_forum_layout"] = FORUM_LAYOUT[forum["layout"]]
        fields["default_auto_archive_duration"] = forum["auto_archive_minutes"]
        fields["available_tags"] = tag_payload(forum["tags"], (existing or {}).get("available_tags", []))
    elif obj.type == "text":
        fields["rate_limit_per_user"] = obj.slow_mode
    return fields


def tag_payload(tags: list[dict], existing: list[dict]) -> list[dict]:
    by_name = {t["name"].lower(): t for t in existing}
    rows = []
    for tag in tags:
        old = by_name.get(tag["name"].lower())
        row = {"name": tag["name"], "moderated": tag["moderated"]}
        if old:
            row["id"] = old["id"]
            for key in ("emoji_id", "emoji_name"):
                if old.get(key) is not None:
                    row[key] = old[key]
        rows.append(row)
    named = {t["name"].lower() for t in tags}
    return rows + [t for t in existing if t["name"].lower() not in named]


def _tags_differ(forum: dict, existing: list[dict]) -> bool:
    mine = [t["name"].lower() for t in forum["tags"]]
    have = {t["name"].lower(): t for t in existing}
    if any(name not in have for name in mine):
        return True
    if [t["name"].lower() for t in existing if t["name"].lower() in mine] != mine:
        return True
    return any(bool(have[t["name"].lower()].get("moderated")) != t["moderated"] for t in forum["tags"])


def field_diffs(obj, fields: dict, existing: dict, is_category: bool) -> list[str]:
    """The names of the settings that differ, in the words the plan uses."""
    diffs = []
    if not is_category:
        if obj.type_id != existing["type"] and existing["type"] in CONVERTIBLE:
            diffs.append("type")
        if fields["parent_id"] is UNKNOWN or (existing.get("parent_id") or None) != fields["parent_id"]:
            diffs.append(f"move to {q(obj.category)}" if obj.category else "move out of its category")
        if "topic" in fields and (existing.get("topic") or "") != fields["topic"]:
            diffs.append("topic")
        if (
            "rate_limit_per_user" in fields
            and (existing.get("rate_limit_per_user") or 0) != fields["rate_limit_per_user"]
        ):
            diffs.append("slow mode")
        if obj.type == "forum":
            forum = obj.forum
            if bool(existing.get("flags", 0) & REQUIRE_TAG) != forum["require_tag"]:
                diffs.append("required tag")
            settings = (
                ("default_sort_order", 0),
                ("default_forum_layout", 0),
                ("default_thread_rate_limit_per_user", 0),
                ("default_auto_archive_duration", None),
            )
            if any((existing.get(k) if existing.get(k) is not None else d) != fields[k] for k, d in settings):
                diffs.append("forum settings")
            if _tags_differ(forum, existing.get("available_tags", [])):
                diffs.append("tags")
    rows = fields["permission_overwrites"]
    if overwrites_differ(existing.get("permission_overwrites", []), rows):
        diffs.append(f"set {len(obj.overwrites)} overwrites")
    return diffs


def _find_channel(ctx: Ctx, name: str, kind: int, parent: str | None) -> dict | None:
    channels = ctx.client.request("GET", f"/guilds/{ctx.gid}/channels")
    for c in channels:
        if c["type"] == kind and norm_channel(c["name"]) == norm_channel(name) and c.get("parent_id") == parent:
            return c
    return None


def _unresolved_ow_labels(
    ctx: Ctx, ch_label: str, existing: dict, rows: list[dict] | None, hidden: bool, step="channels"
) -> list[Change]:
    out = []
    named = {r["id"] for r in rows or []}
    for ow in existing.get("permission_overwrites", []):
        if ow["id"] in named:
            continue
        who = ctx.role_label(ow["id"]) if ow["type"] == 0 else "a member"
        text = f"{ch_label} has an overwrite for {who} that the layout does not name"
        if ctx.opts.prune == "overwrites":
            out.append(Change(step, "delete", f"overwrite for {who} on {ch_label}", None, destructive=True))
        else:
            out.append(Change(step, "warning" if hidden else "unmanaged", text))
    return out


def plan_channels(ctx: Ctx) -> list[Change]:
    layout = ctx.layout
    snap = ctx.snap
    out: list[Change] = []
    matched: set[str] = set()
    cats_existing = [c for c in snap.channels if c["type"] == 4]
    others = [c for c in snap.channels if c["type"] != 4]

    # categories ------------------------------------------------------------------------------
    for cat in layout.categories:
        label = f"category {q(cat.name)}"
        if not cat.enabled:
            out.append(deferred_change(ctx, "channels", label, cat))
            continue
        pool = [c for c in cats_existing if c["id"] not in matched]
        existing = next((c for c in pool if c["name"].lower() == cat.name.lower()), None)
        previous = None
        if existing is None:
            for old in cat.previous_names:
                previous = next((c for c in pool if c["name"].lower() == old.lower()), None)
                if previous:
                    break
        found = existing or previous
        if found is None:
            out.append(_create_object(ctx, cat, True, label))
            continue
        matched.add(found["id"])
        ctx.category_ids[cat.name.lower()] = found["id"]
        out.extend(
            _update_object(
                ctx, cat, True, found, label, hidden=False, renamed_from=previous["name"] if previous else None
            )
        )

    # channels --------------------------------------------------------------------------------
    for ch in layout.channels:
        label = channel_label(ch)
        if not layout.channel_active(ch):
            ctx.unavailable.add(ch.name)
            out.append(deferred_change(ctx, "channels", label, ch))
            continue
        want = norm_channel(ch.name)
        pool = [c for c in others if c["id"] not in matched]
        candidates = [c for c in pool if norm_channel(c["name"]) == want and family(c["type"]) == family(ch.type_id)]
        existing = None
        if candidates:
            right_parent = [
                c for c in candidates if ctx.category_ids.get((ch.category or "").lower()) == c.get("parent_id")
            ]
            existing = (right_parent or candidates)[0]
        previous = None
        if existing is None:
            for old in ch.previous_names:
                options = [
                    c
                    for c in pool
                    if norm_channel(c["name"]) == norm_channel(old) and family(c["type"]) == family(ch.type_id)
                ]
                if options:
                    previous = options[0]
                    break
        found = existing or previous
        if found is None:
            reason = needs_community(snap, ch.type)
            if reason:
                ctx.unavailable.add(ch.name)
                out.append(
                    Change("channels", "blocked", f"{label} ({ch.type}): {reason}", owner_step=_community_step(reason))
                )
                continue
            out.append(_create_object(ctx, ch, False, label))
            continue
        if found["type"] != ch.type_id and not (found["type"] in CONVERTIBLE and ch.type_id in CONVERTIBLE):
            ctx.unavailable.add(ch.name)
            ctx.problems.append(
                f"{label} exists as a different kind of channel and Discord cannot convert it to a {ch.type}. "
                "Rename or remove the old one by hand"
            )
            continue
        if found["type"] != ch.type_id:
            reason = needs_community(snap, ch.type)
            if reason:
                out.append(
                    Change("channels", "blocked", f"{label} ({ch.type}): {reason}", owner_step=_community_step(reason))
                )
                continue
        matched.add(found["id"])
        ctx.channel_ids[ch.name] = found["id"]
        hidden = any(o.target == "@everyone" and o.deny & perms.BIT["view_channel"] for o in ch.overwrites)
        out.extend(
            _update_object(ctx, ch, False, found, label, hidden, renamed_from=previous["name"] if previous else None)
        )

    order = plan_order(ctx)
    out.extend(order)

    # unmanaged ----------------------------------------------------------------------------------
    layout_channel_keys = {(norm_channel(c.name), family(c.type_id)) for c in layout.channels}
    layout_category_names = {c.name.lower() for c in layout.categories}
    unmanaged = []
    for c in others:
        if c["id"] not in matched and (norm_channel(c["name"]), family(c["type"])) not in layout_channel_keys:
            unmanaged.append((c, f"#{c['name']}"))
    for c in cats_existing:
        if c["id"] not in matched and c["name"].lower() not in layout_category_names:
            unmanaged.append((c, f"category {q(c['name'])}"))
    for c, label in unmanaged:
        if ctx.opts.prune == "channels":
            protected = {snap.guild.get("rules_channel_id"), snap.guild.get("public_updates_channel_id")}
            if c["id"] in protected and snap.community:
                out.append(
                    Change(
                        "channels",
                        "unmanaged",
                        f"{label} is the rules or updates channel of the server and cannot be deleted",
                    )
                )
                continue
            out.append(
                _delete(ctx, "channels", label, f"/channels/{c['id']}", f"delete channel {c['name']}", c, snap.channels)
            )
        else:
            out.append(Change("channels", "unmanaged", f"{label} is not in the layout and is left alone"))
    return out


def _community_step(reason: str) -> str:
    return (
        "Enable Community in the server settings, then run this again."
        if "Community" in reason and "NEWS" not in reason
        else ""
    )


def _create_object(ctx: Ctx, obj, is_category: bool, label: str) -> Change:
    kind = 4 if is_category else obj.type_id

    def run():
        fields = desired_fields(ctx, obj, is_category, None)
        if fields is None:
            raise Blocked(f"{label} waits for a role or category that does not exist")
        lockout_check(ctx, label, fields["permission_overwrites"])
        body = {"name": obj.name, "type": kind, **fields}
        if obj.type == "forum" if not is_category else False:
            body["available_tags"] = tag_payload(obj.forum["tags"], [])
        parent = fields.get("parent_id")
        try:
            result = ctx.write(
                "POST",
                f"/guilds/{ctx.gid}/channels",
                body,
                f"create {'category' if is_category else 'channel'} {obj.name}",
                recheck=lambda: _find_channel(ctx, obj.name, kind, parent),
            )
        except ApiError as err:
            if not is_category and obj.type == "forum" and refusal_means_community(err, ctx.snap):
                raise Blocked(f"{label} ({obj.type}): {ANNOUNCEMENT_NEEDS}") from err
            raise
        upsert(ctx.snap.channels, result)
        if is_category:
            ctx.category_ids[obj.name.lower()] = result["id"]
        else:
            ctx.channel_ids[obj.name] = result["id"]

    text = label if is_category else f"{label} ({obj.type})"
    return Change("channels", "create", text, run)


def _update_object(
    ctx: Ctx, obj, is_category: bool, existing: dict, label: str, hidden: bool, renamed_from: str | None
) -> list[Change]:
    fields = desired_fields(ctx, obj, is_category, existing, partial=True)
    diffs = field_diffs(obj, fields, existing, is_category)
    named = {r["id"] for r in fields["permission_overwrites"] or []}
    if ctx.opts.prune == "overwrites" and any(o["id"] not in named for o in existing.get("permission_overwrites", [])):
        diffs.append("remove unmanaged overwrites")
    out: list[Change] = []
    if renamed_from is not None:
        rename_text = f"{'#' + renamed_from if not is_category else 'category ' + q(renamed_from)} -> {label}"
        if not ctx.opts.allow_renames:
            return [Change("channels", "rename", f"{rename_text}: held back, needs --allow-renames", None, held=True)]
        diffs = ["name", *diffs]
    if diffs:

        def run(existing=existing, diffs=diffs):
            fresh = ctx.snap.channel_by_id(existing["id"]) or existing
            wanted = desired_fields(ctx, obj, is_category, fresh)
            if wanted is None:
                raise Blocked(f"{label} waits for a role or category that does not exist")
            body: dict = {}
            if "name" in diffs:
                body["name"] = obj.name
            if fresh["type"] != obj.type_id:
                body["type"] = obj.type_id
            for key, value in wanted.items():
                if key == "permission_overwrites":
                    continue
                if key == "flags":
                    if fresh.get("flags", 0) != value:
                        body[key] = value
                elif key == "available_tags":
                    if _tags_differ(obj.forum, fresh.get("available_tags", [])):
                        body[key] = value
                elif key == "parent_id":
                    if (fresh.get("parent_id") or None) != value:
                        body[key] = value
                elif (fresh.get(key) if fresh.get(key) is not None else (0 if key != "topic" else "")) != value:
                    body[key] = value
            rows = keep_unmanaged(ctx, fresh.get("permission_overwrites", []), wanted["permission_overwrites"])
            if (
                overwrites_differ(fresh.get("permission_overwrites", []), wanted["permission_overwrites"])
                or ctx.opts.prune == "overwrites"
            ):
                body["permission_overwrites"] = rows
            if not body:
                return
            lockout_check(
                ctx, label, rows if "permission_overwrites" in body else fresh.get("permission_overwrites", [])
            )
            result = ctx.write(
                "PATCH",
                f"/channels/{existing['id']}",
                body,
                f"update {'category' if is_category else 'channel'} {obj.name}",
            )
            upsert(ctx.snap.channels, result)

        word = "rename" if renamed_from is not None else "update"
        text = (
            f"{label}: {', '.join(diffs)}"
            if renamed_from is None
            else f"{rename_text}, {', '.join(diffs[1:])}".rstrip(", ")
        )
        out.append(Change("channels", word, text, run, destructive=renamed_from is not None))
    out.extend(_unresolved_ow_labels(ctx, label, existing, fields["permission_overwrites"], hidden))
    return out


def _slot_moves(items: list[dict], desired: list[str]) -> list[dict]:
    """Put the managed items in layout order using only the places they already hold."""
    items = sorted(items, key=lambda i: (i["position"], i["id"]))
    managed = [i for i in items if i["id"] in desired]
    if [i["id"] for i in managed] == [d for d in desired if d in {m["id"] for m in managed}]:
        return []
    order = {d: n for n, d in enumerate(desired)}
    wanted = sorted(managed, key=lambda i: order[i["id"]])
    slots = [i["position"] for i in managed]
    moves = []
    previous = -1
    for item, slot in zip(wanted, slots, strict=True):
        slot = max(slot, previous + 1)
        previous = slot
        if item["position"] != slot:
            moves.append({"id": item["id"], "position": slot})
    return moves


def compute_moves(
    channels: list[dict], layout: Layout, cat_key: dict[str, str], ch_key: dict[str, str]
) -> list[tuple[str, list[dict]]]:
    result = []
    cats = [c for c in channels if c["type"] == 4]
    wanted = [cat_key[c.name.lower()] for c in layout.active_categories if c.name.lower() in cat_key]
    moves = _slot_moves(cats, wanted)
    if moves:
        result.append(("categories", moves))
    for cat in [*layout.active_categories, None]:
        parent = cat_key.get(cat.name.lower()) if cat else None
        if cat is not None and parent is None:
            continue
        items = [c for c in channels if c["type"] != 4 and (c.get("parent_id") or None) == parent]
        wanted = [
            ch_key[ch.name]
            for ch in layout.active_channels
            if (ch.category or None) == (cat.name if cat else None) and ch.name in ch_key
        ]
        moves = _slot_moves(items, wanted)
        if moves:
            result.append((f"channels in {q(cat.name)}" if cat else "channels outside a category", moves))
    return result


def plan_order(ctx: Ctx) -> list[Change]:
    """Whether the categories and channels need reordering once the missing ones exist."""
    layout = ctx.layout
    sim = [dict(c) for c in ctx.snap.channels]
    cat_key = dict(ctx.category_ids)
    ch_key = dict(ctx.channel_ids)
    top = max([c["position"] for c in sim] + [0])
    for cat in layout.active_categories:
        if cat.name.lower() not in cat_key:
            top += 1
            cat_key[cat.name.lower()] = f"new:cat:{cat.name.lower()}"
            sim.append({"id": cat_key[cat.name.lower()], "type": 4, "position": top, "name": cat.name})
    for ch in layout.active_channels:
        if needs_community(ctx.snap, ch.type) and ch.name not in ch_key:
            continue
        parent = cat_key.get(ch.category.lower()) if ch.category else None
        if ch.name in ch_key:
            for c in sim:
                if c["id"] == ch_key[ch.name]:
                    c["parent_id"] = parent
        else:
            top += 1
            ch_key[ch.name] = f"new:{ch.name}"
            sim.append(
                {"id": ch_key[ch.name], "type": ch.type_id, "position": top, "parent_id": parent, "name": ch.name}
            )
    moves = compute_moves(sim, layout, cat_key, ch_key)
    if not moves:
        return []

    def run():
        apply_order(ctx)

    out = [Change("channels", "update", f"order of {label}: {len(m)} moved", None) for label, m in moves]
    out[0].run = run
    return out


def apply_order(ctx: Ctx) -> None:
    cat_key = dict(ctx.category_ids)
    ch_key = dict(ctx.channel_ids)
    moves = compute_moves(ctx.snap.channels, ctx.layout, cat_key, ch_key)
    flat = [m for _, group in moves for m in group]
    if not flat:
        return
    ctx.write("PATCH", f"/guilds/{ctx.gid}/channels", flat, "order channels")
    for move in flat:
        channel = ctx.snap.channel_by_id(move["id"])
        if channel:
            channel["position"] = move["position"]


# ----------------------------------------------------------------------------------------------
# step 5: settings that point at channels


# the screen names are those of Server Settings, Community, Overview and are unconfirmed against the real screen
SCREEN_FOR_POINTER = {
    "rules_channel": "Rules or guidelines channel",
    "public_updates_channel": "Community updates channel",
    "safety_alerts_channel": "Safety alerts channel",
    "system_channel": "System Messages Channel",
}

POINTERS = (
    ("rules_channel", "rules_channel_id", "rules channel"),
    ("public_updates_channel", "public_updates_channel_id", "community updates channel"),
    ("safety_alerts_channel", "safety_alerts_channel_id", "safety alerts channel"),
    # join messages: the channel exists once channels are made, so it is set here and not with the settings
    ("system_channel", "system_channel_id", "system channel"),
)


def plan_pointers(ctx: Ctx) -> list[Change]:
    wanted = [(key, field_name, label) for key, field_name, label in POINTERS if ctx.layout.server.get(key)]
    if not wanted:
        return []
    diffs = []
    for key, field_name, label in wanted:
        name = ctx.layout.server[key]
        current = ctx.snap.guild.get(field_name)
        existing_id = ctx.channel_ids.get(name)
        if existing_id is None or current != existing_id:
            diffs.append((key, field_name, label, name))
    if not diffs:
        return []
    labels = ", ".join(label for _, _, label, _ in diffs)
    if not ctx.snap.community:
        # only the system channel works without Community
        needs = [d for d in diffs if d[0] != "system_channel"]
        diffs = [d for d in diffs if d[0] == "system_channel"]
        blocked = [
            Change(
                "pointers",
                "blocked",
                f"{', '.join(label for _, _, label, _ in needs)}: needs Community",
                owner_step="Enable Community in the server settings, then run this again.",
            )
        ]
        if not needs:
            blocked = []
        if not diffs:
            return blocked
        labels = ", ".join(label for _, _, label, _ in diffs)
        steps = blocked
    else:
        steps = []
    # a pointer that now names a channel the bot cannot see (Discord's own private one, made when Community was
    # switched on) cannot be changed by the bot: Discord answers 403. The owner changes it by hand
    visible = {c["id"] for c in ctx.snap.channels}
    hidden = [d for d in diffs if ctx.snap.guild.get(d[1]) and ctx.snap.guild.get(d[1]) not in visible]
    diffs = [d for d in diffs if d not in hidden]

    def where(name: str) -> str:
        # Discord's own wizard channel has the same name, so the step says which one is ours
        channel = ctx.layout.channel(name)
        return f"under {channel.category}" if channel and channel.category else "from the layout"

    if hidden:
        for key, _, label, name in hidden:
            screen = SCREEN_FOR_POINTER[key]
            steps.append(
                Change(
                    "pointers",
                    "blocked",
                    f"{label}: Discord points it at a private channel the bot cannot see",
                    owner_step=(
                        f'In Server Settings, Community, Overview, set "{screen}" to the #{name} {where(name)}, '
                        "then run this again."
                    ),
                )
            )
    if not diffs:
        return steps
    labels = ", ".join(label for _, _, label, _ in diffs)

    def run():
        body = {}
        for _, field_name, _, name in diffs:
            channel_id = ctx.cid(name)
            if channel_id is None:
                raise Blocked(f"{name} does not exist, so the server cannot point at it")
            body[field_name] = channel_id
        ctx.write("PATCH", f"/guilds/{ctx.gid}", body, "set the rules, updates, safety and system channels")
        ctx.snap.guild.update(body)

    return [*steps, Change("pointers", "update", labels, run)]


# ----------------------------------------------------------------------------------------------
# step 6: auto moderation


def automod_body(ctx: Ctx, rule: dict) -> dict | None:
    trigger = TRIGGERS[rule["trigger"]]
    meta: dict = {}
    if trigger in (1, 6):
        if rule.get("keywords"):
            meta["keyword_filter"] = list(rule["keywords"])
        if rule.get("patterns"):
            meta["regex_patterns"] = list(rule["patterns"])
    if trigger == 4:
        meta["presets"] = [PRESETS[p] for p in rule["presets"]]
    if trigger == 5:
        meta["mention_total_limit"] = rule["mention_total_limit"]
        meta["mention_raid_protection_enabled"] = bool(rule.get("mention_raid_protection", False))
    actions = []
    for action in rule["actions"]:
        kind = ACTIONS[action["type"]]
        metadata: dict = {}
        if action["type"] == "alert":
            channel_id = ctx.cid(action["channel"])
            if channel_id is None:
                return None
            metadata["channel_id"] = channel_id
        elif action["type"] == "timeout":
            metadata["duration_seconds"] = action["seconds"]
        elif action["type"] == "block" and action.get("message"):
            metadata["custom_message"] = action["message"]
        actions.append({"type": kind, "metadata": metadata})
    exempt = []
    for name in rule.get("exempt_roles", []):
        role_id = ctx.rid(name)
        if role_id is None:
            return None
        exempt.append(role_id)
    return {
        "name": rule["name"],
        "event_type": 2 if trigger == 6 else 1,
        "trigger_type": trigger,
        "trigger_metadata": meta,
        "actions": actions,
        "enabled": True,
        "exempt_roles": exempt,
        "exempt_channels": [],
    }


def automod_canon(rule: dict) -> dict:
    meta = rule.get("trigger_metadata") or {}
    actions = sorted(
        (
            {
                "type": a["type"],
                "metadata": {k: v for k, v in (a.get("metadata") or {}).items() if v not in (None, "")},
            }
            for a in rule.get("actions", [])
        ),
        key=lambda a: a["type"],
    )
    return {
        "trigger_type": rule["trigger_type"],
        "event_type": rule["event_type"],
        "keywords": sorted(meta.get("keyword_filter") or []),
        "patterns": sorted(meta.get("regex_patterns") or []),
        "presets": sorted(meta.get("presets") or []),
        "mention_total_limit": meta.get("mention_total_limit"),
        "raid": bool(meta.get("mention_raid_protection_enabled", False)),
        "actions": actions,
        "enabled": bool(rule.get("enabled", True)),
        "exempt_roles": sorted(rule.get("exempt_roles") or []),
    }


def plan_automod(ctx: Ctx) -> list[Change]:
    out: list[Change] = []
    matched: set[str] = set()
    for rule in ctx.layout.automod:
        name = rule["name"]
        label = f"rule {q(name)}"
        existing = next((r for r in ctx.snap.automod if r["name"].lower() == name.lower()), None)
        if existing:
            matched.add(existing["id"])
        if existing is None:
            out.append(Change("automod", "create", label, _automod_run(ctx, rule, None)))
            continue
        if existing["trigger_type"] != TRIGGERS[rule["trigger"]]:
            out.append(
                Change(
                    "automod",
                    "blocked",
                    f"{label}: the kind of trigger differs. Remove the old rule by hand",
                    owner_step=f"Delete the auto moderation rule {q(name)} by hand, then run this again.",
                )
            )
            continue
        body = automod_body(ctx, rule)
        if body is None or automod_canon(body) != automod_canon(existing):
            out.append(Change("automod", "update", label, _automod_run(ctx, rule, existing)))
    for existing in ctx.snap.automod:
        if existing["id"] in matched:
            continue
        label = f"rule {q(existing['name'])}"
        if ctx.opts.prune == "automod":
            out.append(
                _delete(
                    ctx,
                    "automod",
                    label,
                    f"/guilds/{ctx.gid}/auto-moderation/rules/{existing['id']}",
                    f"delete rule {existing['name']}",
                    existing,
                    ctx.snap.automod,
                )
            )
        else:
            out.append(Change("automod", "unmanaged", f"{label} is not in the layout and is left alone"))
    return out


def _automod_run(ctx: Ctx, rule: dict, existing: dict | None):
    def run():
        body = automod_body(ctx, rule)
        if body is None:
            raise Blocked(f"rule {q(rule['name'])} waits for a channel or role that does not exist")
        if existing is None:
            result = ctx.write(
                "POST",
                f"/guilds/{ctx.gid}/auto-moderation/rules",
                body,
                f"create rule {rule['name']}",
                recheck=lambda: next(
                    (
                        r
                        for r in ctx.client.request("GET", f"/guilds/{ctx.gid}/auto-moderation/rules")
                        if r["name"] == rule["name"]
                    ),
                    None,
                ),
            )
        else:
            patch = {k: v for k, v in body.items() if k != "trigger_type"}
            result = ctx.write(
                "PATCH",
                f"/guilds/{ctx.gid}/auto-moderation/rules/{existing['id']}",
                patch,
                f"update rule {rule['name']}",
            )
        upsert(ctx.snap.automod, result)

    return run


# ----------------------------------------------------------------------------------------------
# step 7: onboarding

# the specification names 350000. The first live run answered 400 Invalid Form Body, which is code 50035
ONBOARDING_REFUSED = (350000, 50035)
ONBOARDING_FALLBACK = (
    'Discord refused to switch onboarding on. Set mode = "advanced" under [onboarding] in the layout and run '
    "this again. If it is still refused, make showcase a text channel and switch on introductions."
)


_SNOWFLAKE_COUNTER = itertools.count()


def _new_snowflake() -> str:
    # discord's onboarding endpoint wants an id on every prompt and option, new ones included. it accepts one
    # made by the caller in its own snowflake form: milliseconds since discord's epoch, shifted left 22 bits
    stamp = int(time.time() * 1000) - 1420070400000
    return str((stamp << 22) | (next(_SNOWFLAKE_COUNTER) & 0xFFF))


def onboarding_body(ctx: Ctx, enabled: bool) -> dict | None:
    cfg = ctx.layout.onboarding
    defaults = [ctx.cid(n) for n in cfg.get("default_channels", [])]
    if None in defaults:
        return None
    existing = ctx.snap.onboarding or {}
    old_prompts = {p["title"].lower(): p for p in existing.get("prompts", [])}
    prompts = []
    for prompt in cfg.get("prompts", []):
        old = old_prompts.pop(prompt["title"].lower(), None)
        old_options = {o["title"].lower(): o for o in (old or {}).get("options", [])}
        options = []
        for option in prompt["options"]:
            role_ids = [ctx.rid(r) for r in option.get("roles", [])]
            channel_ids = [ctx.cid(c) for c in option.get("channels", [])]
            if None in role_ids or None in channel_ids:
                return None
            row = {
                "title": option["title"],
                "description": option.get("description", ""),
                "role_ids": role_ids,
                "channel_ids": channel_ids,
            }
            previous = old_options.pop(option["title"].lower(), None)
            row["id"] = previous["id"] if previous else _new_snowflake()
            options.append(row)
        options += [_keep_option(o) for o in old_options.values()]
        row = {
            "title": prompt["title"],
            "type": PROMPT_TYPES[prompt["type"]],
            "single_select": bool(prompt.get("single_select", False)),
            "required": bool(prompt.get("required", False)),
            "in_onboarding": bool(prompt.get("in_onboarding", True)),
            "options": options,
        }
        row["id"] = old["id"] if old else _new_snowflake()
        prompts.append(row)
    prompts += [_keep_prompt(p) for p in old_prompts.values()]
    return {
        "prompts": prompts,
        "default_channel_ids": defaults,
        "enabled": enabled,
        "mode": ONBOARDING_MODES[cfg.get("mode", "default")],
    }


def _keep_option(option: dict) -> dict:
    return {k: option[k] for k in ("id", "title", "description", "role_ids", "channel_ids") if k in option}


def _keep_prompt(prompt: dict) -> dict:
    row = {k: prompt[k] for k in ("id", "title", "type", "single_select", "required", "in_onboarding") if k in prompt}
    row["options"] = [_keep_option(o) for o in prompt.get("options", [])]
    return row


def onboarding_canon(body: dict, titles: set[str] | None = None) -> dict:
    prompts = {}
    for p in body.get("prompts", []):
        if titles is not None and p["title"].lower() not in titles:
            continue
        options = {
            o["title"].lower(): (
                o.get("description") or "",
                sorted(o.get("role_ids", [])),
                sorted(o.get("channel_ids", [])),
            )
            for o in p.get("options", [])
        }
        prompts[p["title"].lower()] = (
            p["type"],
            bool(p.get("single_select")),
            bool(p.get("required")),
            bool(p.get("in_onboarding", True)),
            options,
        )
    return {
        "prompts": prompts,
        "defaults": sorted(body.get("default_channel_ids", [])),
        "enabled": bool(body.get("enabled")),
        "mode": body.get("mode", 0),
    }


def plan_onboarding(ctx: Ctx, unavailable: set[str]) -> list[Change]:
    cfg = ctx.layout.onboarding
    if not cfg:
        return []
    if not ctx.snap.community:
        return [
            Change(
                "onboarding",
                "blocked",
                "onboarding: needs Community",
                owner_step="Enable Community in the server settings, then run this again.",
            )
        ]
    names = set(cfg.get("default_channels", []))
    for prompt in cfg.get("prompts", []):
        for option in prompt["options"]:
            names.update(option.get("channels", []))
    waiting = sorted(names & unavailable)
    if waiting:
        return [Change("onboarding", "blocked", f"onboarding: waits for {', '.join('#' + n for n in waiting)}")]
    want_enabled = bool(cfg.get("enabled", False))
    body = onboarding_body(ctx, want_enabled)
    current = ctx.snap.onboarding
    titles = {p["title"].lower() for p in cfg.get("prompts", [])}
    if body is not None and current is not None:
        mine = onboarding_canon(body)
        theirs = onboarding_canon(current)
        theirs["prompts"] = {k: v for k, v in theirs["prompts"].items() if k in titles}
        mine["prompts"] = {k: v for k, v in mine["prompts"].items() if k in titles}
        if mine == theirs:
            return _onboarding_unmanaged(ctx, current, titles)
    elif current is None and not want_enabled and not cfg.get("prompts"):
        return []
    out = [
        Change(
            "onboarding",
            "update",
            f"onboarding: {len(cfg.get('prompts', []))} question, "
            f"{len(cfg.get('default_channels', []))} default channels, {'enabled' if want_enabled else 'disabled'}",
            _onboarding_run(ctx, want_enabled),
        )
    ]
    return out + _onboarding_unmanaged(ctx, current or {}, titles)


def _onboarding_unmanaged(ctx: Ctx, current: dict, titles: set[str]) -> list[Change]:
    return [
        Change("onboarding", "unmanaged", f"onboarding question {q(p['title'])} is not in the layout and is left alone")
        for p in current.get("prompts", [])
        if p["title"].lower() not in titles
    ]


def _onboarding_run(ctx: Ctx, want_enabled: bool):
    def run():
        already = bool((ctx.snap.onboarding or {}).get("enabled"))
        body = onboarding_body(ctx, already and want_enabled)
        if body is None:
            raise Blocked("onboarding waits for a channel or role that does not exist")
        # the questions are saved first and onboarding is switched on as a separate last move, so a
        # refusal to switch it on leaves the saved questions in place
        ctx.snap.onboarding = ctx.write("PUT", f"/guilds/{ctx.gid}/onboarding", body, "set onboarding questions")
        if want_enabled and not already:
            body = onboarding_body(ctx, True)
            try:
                ctx.snap.onboarding = ctx.write("PUT", f"/guilds/{ctx.gid}/onboarding", body, "switch on onboarding")
            except ApiError as err:
                if err.code in ONBOARDING_REFUSED:
                    raise Blocked(ONBOARDING_FALLBACK) from err
                raise

    return run


# ----------------------------------------------------------------------------------------------
# step 8: texts in channels, as plain messages or as embeds, with every link by id

# the pin list shows the newest pin first in Discord's client and the documentation does not state an order, so
# the messages are pinned last to first. If a real run shows the other order, this is the one place to flip
PIN_NEWEST_FIRST = True
READ_FIRST_TAG = "Read first"


def resolver(ctx: Ctx):
    """Turns {channel:x}, {role:x} and {command:x} into links by id or into plain words when there is no id yet."""

    def resolve(kind: str, name: str) -> str:
        if kind == "channel":
            found = ctx.cid(name)
            return f"<#{found}>" if found else f"#{name}"
        if kind == "role":
            found = ctx.rid(name)
            return f"<@&{found}>" if found else name
        found = ctx.command_ids.get(name.split(" ")[0].lower())
        return f"</{name}:{found}>" if found else f"/{name}"

    return resolve


def render(ctx: Ctx, text: str) -> str:
    return textfmt.render(text, resolver(ctx), contact_email(ctx.layout.commands_content) or "")


def waiting_for_ids(ctx: Ctx, text: str) -> bool:
    """A link to something that is created in this very run cannot be written yet, so the message is written
    again once it exists."""
    for kind, name in textfmt.refs(text):
        if kind == "channel" and name not in ctx.channel_ids and name not in ctx.unavailable:
            return True
        role = ctx.layout.role(name) if kind == "role" else None
        if role is not None and not role.owner and ctx.rid(name) is None:
            return True
        if kind == "command" and name.split(" ")[0].lower() in ctx.planned_commands:
            return True
    return False


def image(ctx: Ctx, key: str) -> tuple[str, bytes]:
    """The brand image with its content hash in the file name. The hash is how a changed image is noticed."""
    path = ctx.layout.base_dir / ctx.layout.brand[key]
    data = path.read_bytes()
    return f"{key}-{hashlib.sha256(data).hexdigest()[:8]}{path.suffix.lower()}", data


def alt_text(ctx: Ctx, filename: str) -> str:
    """The description Discord shows for an uploaded brand image, for people who cannot see it."""
    key = "banner" if filename.startswith("banner-") else "logo"
    return str(ctx.layout.brand.get(f"{key}_alt", ""))


def attachment_rows(ctx: Ctx, rows: list[tuple[object, str]]) -> list[dict]:
    """The attachments array of a message: an id or an upload index, the file name and its alt text."""
    out = []
    for ident, name in rows:
        row: dict = {"id": ident, "filename": name}
        if alt_text(ctx, name):
            row["description"] = alt_text(ctx, name)
        out.append(row)
    return out


def desired_message(ctx: Ctx, ch: Channel, index: int) -> dict:
    text = ch.messages[index]
    if ch.style == "plain":
        return {
            "content": render(ctx, textfmt.plain_markdown(text)),
            "embeds": [],
            "flags": SUPPRESS_EMBEDS,
            "files": [],
            "alts": {},
        }
    title, description = textfmt.split_embed(text)
    logo_name, logo = image(ctx, "logo")
    embed = {
        "title": render(ctx, title),
        "description": render(ctx, description),
        "color": ctx.layout.brand["colour"],
        "thumbnail": {"url": f"attachment://{logo_name}"},
    }
    files = [(logo_name, logo)]
    if ch.banner and index == 0:
        banner_name, banner = image(ctx, "banner")
        embed["image"] = {"url": f"attachment://{banner_name}"}
        files.append((banner_name, banner))
        # the words on the banner image are also written out, so a screen reader finds them
        if ctx.layout.brand.get("tagline"):
            embed["footer"] = {"text": str(ctx.layout.brand["tagline"])}
    alts = {name: alt_text(ctx, name) for name, _ in files}
    return {"content": "", "embeds": [embed], "flags": 0, "files": files, "alts": alts}


IMAGE_NAME = re.compile(r"(banner|logo)-([0-9a-f]{8})[^/?\s]*?\.(?:png|jpe?g|webp|gif)", re.IGNORECASE)


def images_in(message: dict) -> dict[str, str]:
    """The brand images a message holds, as kind -> content hash, read from what Discord returns.

    The documentation says what an attachment object and an embed image carry and nothing about what a stored
    message does to an uploaded file. A file used only by an embed may come back without an attachment entry, the
    embed holding it as a signed CDN address with a query string or as attachment://name. So the name is read
    from every place that can hold it: the attachment file names and the embed image and thumbnail addresses.
    The hash in the name is what says whether the picture changed, so it is matched wherever it sits.
    """
    sources: list[str] = [a.get("filename", "") for a in message.get("attachments", [])]
    for embed in message.get("embeds") or []:
        for key in ("image", "thumbnail"):
            for address in ("url", "proxy_url"):
                sources.append(str((embed.get(key) or {}).get(address, "")))
    found: dict[str, str] = {}
    for source in sources:
        for kind, digest in ((m.group(1).lower(), m.group(2).lower()) for m in IMAGE_NAME.finditer(source)):
            found.setdefault(kind, digest)
    return found


def _alts_by_kind(want: dict) -> dict[str, str]:
    return {next(iter(images_in({"attachments": [{"filename": name}]})), ""): alt for name, alt in want["alts"].items()}


def message_differences(want: dict, old: dict) -> list[str]:
    """What differs between the wanted message and the one in the channel, in words a person can read."""
    reasons: list[str] = []
    old_embeds = old.get("embeds") or []
    if bool(want["embeds"]) != bool(old_embeds):
        reasons.append("style" if want["embeds"] else "style, back to a plain message")
    if want["embeds"] and old_embeds:
        mine, theirs = want["embeds"][0], old_embeds[0]
        if mine["title"] != theirs.get("title") or mine["description"] != theirs.get("description"):
            reasons.append("text")
        if mine["color"] != theirs.get("color"):
            reasons.append("accent colour")
        if (mine.get("footer") or {}).get("text") != (theirs.get("footer") or {}).get("text"):
            reasons.append("tagline")
    if (old.get("content") or "") != want["content"]:
        reasons.append("text")
    if bool(old.get("flags", 0) & SUPPRESS_EMBEDS) != bool(want["flags"] & SUPPRESS_EMBEDS):
        reasons.append("embed flag")
    have = images_in(old)
    wanted = images_in({"attachments": [{"filename": name} for name, _ in want["files"]]})
    if have != wanted:
        for kind in sorted(set(have) ^ set(wanted) | {k for k in have if k in wanted and have[k] != wanted[k]}):
            label = f"{kind} image"
            if label not in reasons:
                reasons.append(label)
    elif want["embeds"] and old.get("attachments"):
        # the alt text lives on the attachment, so it can be compared only when Discord returns the attachments
        said = {
            kind: a.get("description", "")
            for a in old["attachments"]
            for kind in [next(iter(images_in({"attachments": [a]})), "")]
        }
        if any(alt != said.get(kind, "") for kind, alt in _alts_by_kind(want).items()):
            reasons.append("alt text")
    return list(dict.fromkeys(reasons))


def plan_messages(ctx: Ctx, unavailable: set[str]) -> list[Change]:
    out: list[Change] = []
    for ch in ctx.layout.active_channels:
        if not ch.messages or ch.name in unavailable:
            continue
        existing_channel = ctx.snap.channel_by_id(ctx.cid(ch.name)) if ctx.cid(ch.name) else None
        have: list[dict] = []
        if existing_channel:
            try:
                have = bot_messages(ctx.client, existing_channel["id"], ctx.bot_id, len(ch.messages))
            except ApiError as err:
                if err.status in (403, 404):
                    out.append(Change("messages", "blocked", f"#{ch.name}: the bot cannot read its messages here"))
                    continue
                raise
        for index, text in enumerate(ch.messages):
            label = f"message {index + 1} of {len(ch.messages)} in #{ch.name}"
            if index >= len(have):
                out.append(Change("messages", "create", label, _message_run(ctx, ch, index, None)))
                continue
            old = have[index]
            reasons = message_differences(desired_message(ctx, ch, index), old)
            if waiting_for_ids(ctx, text) and not reasons:
                reasons = ["links"]
            if reasons:
                out.append(
                    Change("messages", "update", f"{label}: {', '.join(reasons)}", _message_run(ctx, ch, index, old))
                )
        for extra in have[len(ch.messages) :]:
            label = f"a message of the bot in #{ch.name} that the layout does not hold"
            if ctx.opts.prune == "messages":
                out.append(Change("messages", "delete", label, _message_delete_run(ctx, ch, extra), destructive=True))
            else:
                out.append(Change("messages", "unmanaged", f"{label} and is left alone"))
    return out


def _message_delete_run(ctx: Ctx, ch: Channel, message: dict):
    def run():
        ctx.write(
            "DELETE", f"/channels/{ctx.cid(ch.name)}/messages/{message['id']}", None, f"delete message in {ch.name}"
        )

    return run


def _message_run(ctx: Ctx, ch: Channel, index: int, old: dict | None):
    def run():
        channel_id = ctx.cid(ch.name)
        if channel_id is None:
            raise Blocked(f"#{ch.name} does not exist yet")
        want = desired_message(ctx, ch, index)
        body = {
            "content": want["content"],
            "embeds": want["embeds"],
            "flags": want["flags"],
            # nothing a managed message says may ever ping, a role link included
            "allowed_mentions": {"parse": []},
        }
        files = want["files"] or None
        if want["embeds"]:
            body["attachments"] = attachment_rows(ctx, [(n, name) for n, (name, _) in enumerate(want["files"])])
        else:
            body["attachments"] = []
        if old is None:
            before = {m["id"] for m in bot_messages(ctx.client, channel_id, ctx.bot_id)}

            def recheck():
                # a post that was retried after a server error may already be there. Look before posting again
                fresh = bot_messages(ctx.client, channel_id, ctx.bot_id)
                return next(
                    (
                        m
                        for m in fresh
                        if m["id"] not in before
                        and m["content"] == body["content"]
                        and (m.get("embeds") or [{}])[0].get("title") == (body["embeds"] or [{}])[0].get("title")
                    ),
                    None,
                )

            ctx.write(
                "POST",
                f"/channels/{channel_id}/messages",
                body,
                f"post message {index + 1} in {ch.name}",
                recheck=recheck,
                files=files,
            )
            return
        have = {a["filename"]: a["id"] for a in old.get("attachments", [])}
        if want["embeds"] and set(have) == {name for name, _ in want["files"]} and have:
            # the images are already there. Keep them and change only the text, so nothing is uploaded again
            body["attachments"] = [
                {"id": have[name], **({"description": want["alts"][name]} if want["alts"][name] else {})}
                for name, _ in want["files"]
            ]
            files = None
        ctx.write(
            "PATCH",
            f"/channels/{channel_id}/messages/{old['id']}",
            body,
            f"edit message {index + 1} in {ch.name}",
            files=files,
        )

    return run


# ----------------------------------------------------------------------------------------------
# a forum's pinned "Read first" post

PINNED_FLAG = 1 << 1


def readfirst_embed(ctx: Ctx, ch: Channel) -> dict:
    title, description = textfmt.split_embed(read_first_text(ctx.layout, ch))
    return {"title": render(ctx, title), "description": render(ctx, description), "color": ctx.layout.brand["colour"]}


ARCHIVE_PAGES = 10


def forum_threads(ctx: Ctx, forum_id: str) -> list[dict]:
    """Every post in a forum the bot can list: the active ones and the archived public ones."""
    found = [
        t for t in ctx.client.request("GET", f"/guilds/{ctx.gid}/threads/active").get("threads", [])
        if t.get("parent_id") == forum_id
    ]  # fmt: skip
    before = None
    for _ in range(ARCHIVE_PAGES):
        path = f"/channels/{forum_id}/threads/archived/public?limit=50" + (f"&before={before}" if before else "")
        try:
            page = ctx.client.request("GET", path)
        except ApiError as err:
            if err.status in (403, 404):
                break  # without Read Message History the archived posts cannot be listed: the active ones stand
            raise
        threads = page.get("threads", [])
        found += threads
        if not page.get("has_more") or not threads:
            break
        before = threads[-1]["thread_metadata"]["archive_timestamp"]
    return found


def find_readfirst(ctx: Ctx, forum_id: str, name: str, tag_id: str | None = None) -> list[dict]:
    """The posts the bot made as Read first posts, best first.

    A post is the bot's own when the bot owns it and it carries the Read first tag or still bears the exact
    title. An archived post and a post whose first line was edited since both count, so there is never a second one.
    """
    mine = [
        t
        for t in forum_threads(ctx, forum_id)
        if t.get("owner_id") == ctx.bot_id and ((tag_id and tag_id in t.get("applied_tags", [])) or t["name"] == name)
    ]

    def rank(t: dict) -> tuple:
        archived = bool((t.get("thread_metadata") or {}).get("archived"))
        return (archived, not t.get("flags", 0) & PINNED_FLAG, -int(t["id"]))

    return sorted(mine, key=rank)


def _read_first_tag(forum: dict | None) -> str | None:
    tag = next((t for t in (forum or {}).get("available_tags", []) if t["name"] == READ_FIRST_TAG), None)
    return tag["id"] if tag else None


def plan_readfirst(ctx: Ctx, unavailable: set[str]) -> list[Change]:
    out: list[Change] = []
    for ch in ctx.layout.active_channels:
        if not ch.read_first or ch.name in unavailable:
            continue
        label = f"the Read first post in #{ch.name}"
        forum_id = ctx.cid(ch.name)
        title = textfmt.split_embed(read_first_text(ctx.layout, ch))[0]
        posts: list[dict] = []
        others_pinned: list[dict] = []
        if forum_id and ctx.snap.channel_by_id(forum_id):
            posts = find_readfirst(ctx, forum_id, title, _read_first_tag(ctx.snap.channel_by_id(forum_id)))
            ours = {t["id"] for t in posts}
            others_pinned = [
                t
                for t in forum_threads(ctx, forum_id)
                if t.get("flags", 0) & PINNED_FLAG and t["id"] not in ours and not t["thread_metadata"]["archived"]
            ]
        existing = posts[0] if posts else None
        # Discord keeps one pinned post per forum. A post somebody pinned by hand is theirs: say so, never fail on it
        conflict = bool(others_pinned) and not (existing and existing.get("flags", 0) & PINNED_FLAG)
        if existing is None:
            out.append(Change("readfirst", "create", label, _readfirst_run(ctx, ch, None, pin=not conflict)))
        else:
            archived = bool(existing["thread_metadata"]["archived"])
            starter = ctx.client.request("GET", f"/channels/{existing['id']}/messages/{existing['id']}")
            mine = readfirst_embed(ctx, ch)
            theirs = (starter.get("embeds") or [{}])[0]
            reasons = []
            if mine["description"] != theirs.get("description") or mine["title"] != theirs.get("title"):
                reasons.append("text")
            if mine["color"] != theirs.get("color"):
                reasons.append("accent colour")
            if existing["name"] != mine["title"]:
                reasons.append("post name")
            if archived:
                reasons.append("reopen it")
            if not existing.get("flags", 0) & PINNED_FLAG and not conflict:
                reasons.append("pin")
            if reasons:
                out.append(
                    Change(
                        "readfirst",
                        "update",
                        f"{label}: {', '.join(reasons)}",
                        _readfirst_run(ctx, ch, existing, pin=not conflict),
                    )
                )
            for _ in posts[1:]:
                out.append(Change("readfirst", "unmanaged", f"a second Read first post in #{ch.name} is left alone"))
        if conflict:
            their = others_pinned[0]["name"]
            out.append(
                Change(
                    "readfirst",
                    "blocked",
                    f"{label}: Discord allows one pinned post per forum and {q(their)} is pinned already",
                    owner_step=(
                        f"In #{ch.name} unpin {q(their)} or leave it and pin the Read first post by hand, "
                        "then run this again."
                    ),
                )
            )
    return out


def _readfirst_run(ctx: Ctx, ch: Channel, existing: dict | None, pin: bool = True):
    def run():
        forum = ctx.snap.channel_by_id(ctx.cid(ch.name) or "")
        if forum is None:
            raise Blocked(f"#{ch.name} does not exist yet")
        embed = readfirst_embed(ctx, ch)
        message = {"embeds": [embed], "flags": 0, "allowed_mentions": {"parse": []}}
        if existing is None:
            tag_id = _read_first_tag(forum)
            if tag_id is None:
                raise Blocked(f'#{ch.name} has no "{READ_FIRST_TAG}" tag yet')
            body = {
                "name": embed["title"],
                "auto_archive_duration": 10080,
                "applied_tags": [tag_id],
                "message": message,
            }
            thread = ctx.write(
                "POST",
                f"/channels/{forum['id']}/threads",
                body,
                f"post the read first post in {ch.name}",
                recheck=lambda: next(iter(find_readfirst(ctx, forum["id"], embed["title"], tag_id)), None),
            )
        else:
            thread = existing
            if existing["thread_metadata"]["archived"]:
                # a message in an archived post cannot be edited until it is open again
                ctx.write(
                    "PATCH",
                    f"/channels/{thread['id']}",
                    {"archived": False},
                    f"reopen the read first post in {ch.name}",
                )
            ctx.write(
                "PATCH",
                f"/channels/{thread['id']}/messages/{thread['id']}",
                message,
                f"edit the read first post in {ch.name}",
            )
            if thread["name"] != embed["title"]:
                ctx.write(
                    "PATCH",
                    f"/channels/{thread['id']}",
                    {"name": embed["title"]},
                    f"rename the read first post in {ch.name}",
                )
        if pin and not (
            thread.get("flags", 0) & PINNED_FLAG and not (thread.get("thread_metadata") or {}).get("archived")
        ):
            # "the PINNED flag is for forum posts" (the channel page). Setting it needs Manage Threads
            try:
                ctx.write(
                    "PATCH",
                    f"/channels/{thread['id']}",
                    {"flags": thread.get("flags", 0) | PINNED_FLAG},
                    f"pin the read first post in {ch.name}",
                )
            except ApiError as err:
                if err.code == 30047:
                    raise Blocked(f"#{ch.name} already has a pinned post, which Discord allows only once") from None
                raise

    return run


# ----------------------------------------------------------------------------------------------
# pins


def list_pins(client: Client, channel_id: str) -> list[str]:
    """The ids of the pinned messages in the order the API lists them."""
    return [m["id"] for m in pinned_messages(client, channel_id)]


def plan_pins(ctx: Ctx, unavailable: set[str]) -> list[Change]:
    """Pin each managed message, in order and never touch a pin the tool did not make."""
    out: list[Change] = []
    for ch in ctx.layout.active_channels:
        if not ch.pin or not ch.messages or ch.name in unavailable:
            continue
        count = len(ch.messages)
        channel = ctx.snap.channel_by_id(ctx.cid(ch.name)) if ctx.cid(ch.name) else None
        label = f"{count} messages in #{ch.name}"
        if channel is None:
            out.append(Change("pins", "create", f"pin {label}", _pin_run(ctx, ch)))
            continue
        try:
            have = bot_messages(ctx.client, channel["id"], ctx.bot_id, count)[:count]
            pinned = list_pins(ctx.client, channel["id"])
        except ApiError as err:
            if err.status in (403, 404):
                out.append(Change("pins", "blocked", f"#{ch.name}: the bot cannot read the pins here"))
                continue
            raise
        managed = [m["id"] for m in have]
        if len(managed) < count:
            out.append(Change("pins", "create", f"pin {label}", _pin_run(ctx, ch)))
            continue
        ours = [i for i in pinned if i in managed]
        if ours == managed:
            continue
        if not ours:
            out.append(Change("pins", "create", f"pin {label}", _pin_run(ctx, ch)))
        else:
            out.append(
                Change("pins", "update", f"pins in #{ch.name}: put the {count} messages in order", _pin_run(ctx, ch))
            )
    return out


def _pin_run(ctx: Ctx, ch: Channel):
    def run():
        channel_id = ctx.cid(ch.name)
        if channel_id is None:
            raise Blocked(f"#{ch.name} does not exist yet")
        managed = [
            m["id"] for m in bot_messages(ctx.client, channel_id, ctx.bot_id, len(ch.messages))[: len(ch.messages)]
        ]
        if len(managed) < len(ch.messages):
            raise Blocked(f"the messages of #{ch.name} are not all there yet")
        everything = {m["id"] for m in ctx.client.request("GET", f"/channels/{channel_id}/messages?limit=100")}
        pinned = list_pins(ctx.client, channel_id)
        # only the tool's own pins are ever removed and only to put them back in order
        for message_id in [i for i in pinned if i in managed]:
            ctx.write(
                "DELETE", f"/channels/{channel_id}/messages/pins/{message_id}", None, f"unpin message in {ch.name}"
            )
        for message_id in reversed(managed) if PIN_NEWEST_FIRST else managed:
            ctx.write("PUT", f"/channels/{channel_id}/messages/pins/{message_id}", None, f"pin message in {ch.name}")
        # each pin leaves a "pinned a message" notice (type 6) written by the bot. Remove the ones just made
        for message in ctx.client.request("GET", f"/channels/{channel_id}/messages?limit=100"):
            if message.get("type") == 6 and message["author"]["id"] == ctx.bot_id and message["id"] not in everything:
                ctx.write("DELETE", f"/channels/{channel_id}/messages/{message['id']}", None, "remove the pin notice")

    return run


# ----------------------------------------------------------------------------------------------
# step 9: webhooks


def plan_webhooks(ctx: Ctx, unavailable: set[str]) -> list[Change]:
    out: list[Change] = []
    matched: set[str] = set()
    app_id = ctx.snap.app["id"]
    names = {h["name"].lower() for h in ctx.layout.webhooks}
    for wanted in ctx.opts.rotate:
        if wanted.lower() not in names:
            raise SetupError(f"--rotate-webhook names {q(wanted)}, which is not a webhook in the layout")
    for hook in ctx.layout.webhooks:
        channel = ctx.layout.channel(hook["channel"])
        label = f"{q(hook['name'])} in #{hook['channel']}"
        if channel is None or not ctx.layout.channel_active(channel):
            continue
        if hook["channel"] in unavailable:
            out.append(Change("webhooks", "blocked", f"{label}: the channel is not there yet"))
            continue
        channel_id = ctx.cid(hook["channel"])
        existing = next(
            (
                w
                for w in ctx.snap.webhooks
                if w.get("application_id") == app_id
                and w["channel_id"] == channel_id
                and w["name"].lower() == hook["name"].lower()
            ),
            None,
        )
        if existing:
            matched.add(existing["id"])
        if existing is None:
            out.append(Change("webhooks", "create", label, _webhook_create(ctx, hook)))
        elif hook["name"].lower() in {r.lower() for r in ctx.opts.rotate}:
            out.append(
                Change(
                    "webhooks",
                    "rotate",
                    f"{label}: delete and create again for a new address",
                    _webhook_rotate(ctx, hook, existing),
                    destructive=True,
                )
            )
    for w in ctx.snap.webhooks:
        if w["id"] in matched:
            continue
        channel = ctx.snap.channel_by_id(w["channel_id"])
        where = f"#{channel['name']}" if channel else "a channel"
        label = f"webhook {q(w['name'])} in {where}"
        if ctx.opts.prune == "webhooks":
            out.append(
                _delete(
                    ctx, "webhooks", label, f"/webhooks/{w['id']}", f"delete webhook {w['name']}", w, ctx.snap.webhooks
                )
            )
        else:
            out.append(Change("webhooks", "unmanaged", f"{label} is not in the layout and is left alone"))
    return out


def _webhook_create(ctx: Ctx, hook: dict):
    def run():
        channel_id = ctx.cid(hook["channel"])
        if channel_id is None:
            raise Blocked(f"#{hook['channel']} does not exist yet")

        def recheck():
            hooks = ctx.client.request("GET", f"/channels/{channel_id}/webhooks")
            return next((w for w in hooks if w["name"] == hook["name"]), None)

        result = ctx.write(
            "POST",
            f"/channels/{channel_id}/webhooks",
            {"name": hook["name"]},
            f"create webhook {hook['name']}",
            recheck=recheck,
        )
        ctx.snap.webhooks.append({k: v for k, v in result.items() if k not in ("token", "url")})

    return run


def _webhook_rotate(ctx: Ctx, hook: dict, existing: dict):
    def run():
        ctx.write("DELETE", f"/webhooks/{existing['id']}", None, f"delete webhook {hook['name']} to rotate it")
        ctx.snap.webhooks[:] = [w for w in ctx.snap.webhooks if w["id"] != existing["id"]]
        _webhook_create(ctx, hook)()

    return run


# ----------------------------------------------------------------------------------------------
# step 10: commands and step 11: the interactions address


def plan_commands(ctx: Ctx) -> list[Change]:
    layout = ctx.layout
    if not layout.commands.get("content"):
        return []
    if layout.commands_content is None:
        return [Change("commands", "blocked", "commands: the content file is missing")]
    wanted, errors = commandset.registration(layout.commands_content, bool(layout.status.get("enabled", False)))
    ctx.problems.extend(errors)
    have = {(c["name"], c.get("type", 1)): c for c in ctx.snap.commands}
    want_keys = {(c["name"], c["type"]) for c in wanted}
    out: list[Change] = []
    for command in wanted:
        key = (command["name"], command["type"])
        label = f"command /{command['name']}" if command["type"] == 1 else f"message command {q(command['name'])}"
        if key not in have:
            ctx.planned_commands.add(command["name"].lower())
            out.append(Change("commands", "create", label))
        elif commandset.canonical(have[key]) != commandset.canonical(command):
            out.append(Change("commands", "update", label))
    retired = {n.lower() for n in layout.commands.get("retired", [])}
    unmanaged = [c for k, c in have.items() if k not in want_keys and c["name"].lower() not in retired]
    gone = [c for k, c in have.items() if k not in want_keys and c["name"].lower() in retired]
    for c in gone:
        # a command the tool itself registered earlier and the layout now lists as retired. Nobody else made it
        out.append(Change("commands", "delete", f"command /{c['name']}: retired in the layout"))
    for c in unmanaged:
        label = f"command {q(c['name'])}"
        if ctx.opts.prune == "commands":
            out.append(Change("commands", "delete", label, destructive=True))
        else:
            out.append(Change("commands", "unmanaged", f"{label} is not in the layout and is left alone"))
    changing = [c for c in out if c.word in ("create", "update", "delete")]
    if changing:

        def run():
            body = list(wanted)
            if ctx.opts.prune != "commands":
                body += [commandset.writable(c) for c in unmanaged]
            result = ctx.write(
                "PUT",
                f"/applications/{ctx.snap.app['id']}/guilds/{ctx.gid}/commands",
                body,
                "register commands",
            )
            ctx.snap.commands = result
            ctx.command_ids = {c["name"].lower(): c["id"] for c in result if c.get("type", 1) == 1}
            ctx.planned_commands.clear()

        changing[0].run = run
        for other in changing[1:]:
            other.follows = changing[0]
    return out


def plan_application(ctx: Ctx, url: str | None) -> list[Change]:
    if not url:
        return []
    if ctx.snap.app.get("interactions_endpoint_url") == url:
        return []

    def run():
        ctx.write("PATCH", "/applications/@me", {"interactions_endpoint_url": url}, "set the interactions address")
        ctx.snap.app["interactions_endpoint_url"] = url

    return [Change("application", "update", "interactions address of the application", run)]
