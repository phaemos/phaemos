"""Loads and validates a layout file and the texts it points at. No network."""

from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from serverkit import perms, textfmt
from serverkit.style import identifier_problems, style_problems

SCHEMA = 1
CHANNEL_TYPES = {"text": 0, "voice": 2, "category": 4, "announcement": 5, "stage": 13, "forum": 15}
FORUM_SORT = {"latest_activity": 0, "creation_date": 1}
FORUM_LAYOUT = {"list": 1, "gallery": 2}
AUTO_ARCHIVE = (60, 1440, 4320, 10080)
VERIFICATION_LEVELS = range(5)
MESSAGE_LIMIT = 2000
CHANNEL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SECRET_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
BANNED_WEBHOOK_WORDS = ("discord", "clyde")

TRIGGERS = {"keyword": 1, "spam": 3, "keyword_preset": 4, "mention_spam": 5, "member_profile": 6}
TRIGGER_LIMITS = {"keyword": 6, "spam": 1, "keyword_preset": 1, "mention_spam": 1, "member_profile": 1}
PRESETS = {"profanity": 1, "sexual_content": 2, "slurs": 3}
ACTIONS = {"block": 1, "alert": 2, "timeout": 3, "block_interaction": 4}
PROMPT_TYPES = {"multiple_choice": 0, "dropdown": 1}
ONBOARDING_MODES = {"default": 0, "advanced": 1}
ONBOARDING_CHANNEL_TYPES = ("text", "announcement", "forum")

# unconfirmed in the specification: whether a forum counts towards the five channels that everyone
# must be able to post in before onboarding can be switched on. Kept in one place. The first live apply was refused
# with 10 defaults, of which 2 were plain channels everyone can write in and 3 were forums, so forums count for
# nothing here.
FORUMS_COUNT_FOR_ONBOARDING = False


class LayoutError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class Overwrite:
    target: str
    allow: int = 0
    deny: int = 0


@dataclass
class Role:
    name: str
    permissions: int
    hoist: bool
    mentionable: bool
    colour: int
    previous_names: list[str] = field(default_factory=list)
    # an owner role is made and edited by hand in Discord's settings. The script only reads it and reports
    # every difference from the layout. It sits above the bot's own role, so a stolen token cannot hand it out
    owner: bool = False


@dataclass
class Category:
    name: str
    overwrites: list[Overwrite]
    staff: bool = False
    enabled: bool = True
    threshold: str = ""
    threshold_members: int | None = None
    previous_names: list[str] = field(default_factory=list)


@dataclass
class Channel:
    name: str
    category: str | None
    type: str
    topic: str
    slow_mode: int
    own_overwrites: list[Overwrite]
    overwrites: list[Overwrite]
    forum: dict | None
    messages: list[str]
    staff: bool = False
    # how the managed messages are posted, whether the first carries the banner and whether they are pinned
    style: str = "plain"
    banner: bool = False
    pin: bool = False
    # a forum's pinned "Read first" post: the text of this file, with {guidelines} and {faq} filled in
    read_first: str = ""
    enabled: bool = True
    threshold: str = ""
    threshold_members: int | None = None
    previous_names: list[str] = field(default_factory=list)

    @property
    def type_id(self) -> int:
        return CHANNEL_TYPES[self.type]


@dataclass
class Layout:
    path: Path
    base_dir: Path
    hash8: str
    server: dict
    sets: dict[str, int]
    everyone: int
    roles: list[Role]
    categories: list[Category]
    channels: list[Channel]
    automod: list[dict]
    onboarding: dict
    webhooks: list[dict]
    commands: dict
    commands_content: dict | None
    status: dict
    relay: dict
    brand: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.server["name"]

    def category(self, name: str) -> Category | None:
        return next((c for c in self.categories if c.name.lower() == name.lower()), None)

    def channel(self, name: str) -> Channel | None:
        return next((c for c in self.channels if c.name == name), None)

    def role(self, name: str) -> Role | None:
        return next((r for r in self.roles if r.name.lower() == name.lower()), None)

    def channel_active(self, channel: Channel) -> bool:
        if not channel.enabled:
            return False
        if channel.category:
            category = self.category(channel.category)
            return category is not None and category.enabled
        return True

    @property
    def active_channels(self) -> list[Channel]:
        return [c for c in self.channels if self.channel_active(c)]

    @property
    def active_categories(self) -> list[Category]:
        return [c for c in self.categories if c.enabled]

    def overwrite_masks(self) -> list[int]:
        """Every permission mask named by a role or an overwrite, for working out what the bot holds."""
        masks = [self.everyone, *(r.permissions for r in self.roles)]
        for category in self.categories:
            masks.extend(o.allow | o.deny for o in category.overwrites)
        for channel in self.channels:
            masks.extend(o.allow | o.deny for o in channel.own_overwrites)
        return masks

    def bot_permissions(self, waiting: bool = False, staff_setup: bool = False) -> int:
        """The permissions the bot needs: the base set plus whatever it may hand on.

        Channels and categories that wait are left out, since nothing is written for them yet. With `waiting`
        they count, which is how the access check asks, so a layout is checked as it will be once they are on.
        """
        needed = perms.required_for_bot([self.everyone, *(r.permissions for r in self.roles if not r.owner)])
        for category in self.categories if waiting else self.active_categories:
            for o in category.overwrites:
                needed |= o.allow | o.deny
        for channel in self.channels if waiting else self.active_channels:
            for o in channel.own_overwrites:
                needed |= o.allow | o.deny
        if staff_setup:
            # while the bot sets the owner's roles up it must hold what it puts on them. Kick, ban and mention
            # everyone stay out: the owner switches those on by hand
            for role in self.roles:
                if role.owner:
                    needed |= role.permissions
        return needed & ~perms.OWNER_ONLY_MASK

    def lines_to_check(self) -> list[tuple[str, str]]:
        """Every member-facing string with a label, for the style checks."""
        items: list[tuple[str, str]] = [("server description", self.server.get("description", ""))]
        items += [
            (f"brand {key}", str(self.brand[key]))
            for key in ("tagline", "logo_alt", "banner_alt")
            if self.brand.get(key)
        ]
        items += [(f"role {r.name}", r.name) for r in self.roles]
        items += [(f"category {c.name}", c.name) for c in self.categories]
        for ch in self.channels:
            items.append((f"channel {ch.name} name", ch.name))
            items.append((f"channel {ch.name} topic", ch.topic))
            for index, message in enumerate(ch.messages, 1):
                items.append((f"channel {ch.name} message {index}", message))
            if ch.read_first:
                items.append((f"channel {ch.name} read first", read_first_text(self, ch)))
            for tag in (ch.forum or {}).get("tags", []):
                items.append((f"channel {ch.name} tag {tag['name']}", tag["name"]))
        for rule in self.automod:
            items.append((f"auto moderation {rule['name']} name", rule["name"]))
            for action in rule.get("actions", []):
                if action.get("message"):
                    items.append((f"auto moderation {rule['name']} message", action["message"]))
        for prompt in self.onboarding.get("prompts", []):
            items.append(("onboarding question", prompt["title"]))
            for option in prompt["options"]:
                items.append((f"onboarding option {option['title']}", option["title"]))
                items.append((f"onboarding option {option['title']} description", option.get("description", "")))
        items += [(f"webhook {w['name']}", w["name"]) for w in self.webhooks]
        return items


def _expand(names: list[str], sets: dict[str, int], where: str, errors: list[str]) -> int:
    value = 0
    for name in names:
        if name.startswith("@"):
            if name[1:] not in sets:
                errors.append(f"{where}: unknown permission set {name}")
                continue
            value |= sets[name[1:]]
        elif name in perms.BIT:
            value |= perms.BIT[name]
        else:
            errors.append(f"{where}: unknown permission {name}")
    return value


def _overwrites(raw: list[dict], sets: dict[str, int], where: str, errors: list[str]) -> list[Overwrite]:
    result = []
    for entry in raw:
        target = entry.get("target", "")
        allow = _expand(entry.get("allow", []), sets, f"{where} allow", errors)
        deny = _expand(entry.get("deny", []), sets, f"{where} deny", errors)
        if allow & deny:
            errors.append(f"{where}: {target} both allows and denies {', '.join(perms.names_of(allow & deny))}")
        result.append(Overwrite(target, allow, deny))
    return result


def _structural(value: int) -> list[str]:
    return perms.names_of(value & perms.STRUCTURAL_MASK)


def _read(path: Path, errors: list[str], where: str) -> str:
    if not path.is_file():
        errors.append(f"{where}: file {path.name} not found")
        return ""
    return path.read_text(encoding="utf-8").rstrip("\n")


def merge_overwrites(inherited: list[Overwrite], own: list[Overwrite]) -> list[Overwrite]:
    """A channel carries its category's rows. A row of its own for the same target replaces one."""
    merged = {o.target: o for o in inherited}
    for o in own:
        merged[o.target] = o
    return list(merged.values())


def load(path: str | Path, base_dir: str | Path | None = None) -> Layout:
    path = Path(path)
    errors: list[str] = []
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise LayoutError([f"cannot read {path}: {exc.strerror}"]) from None
    try:
        raw = tomllib.loads(data.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise LayoutError([f"{path.name} is not valid TOML: {exc}"]) from None
    base = Path(base_dir) if base_dir else path.parent.parent
    hash8 = hashlib.sha256(data).hexdigest()[:8]

    if raw.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")

    server = raw.get("server", {})
    for key in ("name", "description", "preferred_locale"):
        if not isinstance(server.get(key), str) or not server.get(key):
            errors.append(f"server.{key} is required")
    if server.get("verification_level") not in VERIFICATION_LEVELS:
        errors.append("server.verification_level must be 0 to 4")
    if server.get("explicit_content_filter") not in (0, 1, 2):
        errors.append("server.explicit_content_filter must be 0, 1 or 2")
    if server.get("default_message_notifications") not in (0, 1):
        errors.append("server.default_message_notifications must be 0 or 1")
    if len(server.get("name", "")) > 100 or len(server.get("name", "")) < 2:
        errors.append("server.name must be 2 to 100 characters")

    sets: dict[str, int] = {}
    for name, names in raw.get("permission_sets", {}).items():
        sets[name] = _expand(names, {}, f"permission set {name}", errors)
    everyone = _expand(raw.get("everyone", {}).get("permissions", []), sets, "everyone", errors)
    if _structural(everyone):
        errors.append(f"everyone may not hold {', '.join(_structural(everyone))}")
    if everyone & perms.OWNER_ONLY_MASK:
        errors.append("everyone may not hold kick_members, ban_members or mention_everyone")

    roles: list[Role] = []
    seen_roles: set[str] = set()
    for entry in raw.get("roles", []):
        name = entry.get("name", "")
        if not name or len(name) > 100:
            errors.append("a role needs a name of 1 to 100 characters")
        if name.lower() in seen_roles or name.lower() == "@everyone":
            errors.append(f"role {name} is listed twice or reserved")
        seen_roles.add(name.lower())
        value = _expand(entry.get("permissions", []), sets, f"role {name}", errors)
        if _structural(value):
            errors.append(f"role {name} may not hold {', '.join(_structural(value))}")
        colour = entry.get("colour", 0)
        if not isinstance(colour, int) or not 0 <= colour <= 0xFFFFFF:
            errors.append(f"role {name}: colour must be a number from 0 to 16777215")
        roles.append(
            Role(
                name,
                value,
                bool(entry.get("hoist", False)),
                bool(entry.get("mentionable", False)),
                colour if isinstance(colour, int) else 0,
                list(entry.get("previous_names", [])),
                bool(entry.get("owner", False)),
            )
        )
    seen_managed = False
    for role in roles:
        if role.owner and seen_managed:
            errors.append(f"owner role {role.name} must be listed before the roles the script manages")
        if not role.owner:
            seen_managed = True
            if role.permissions & perms.OWNER_ONLY_MASK:
                errors.append(
                    f"role {role.name} is managed by the script, which can never grant kick, ban or mention everyone"
                )
    if len(roles) > 240:
        errors.append("a server holds at most 250 roles")

    valid_targets = {"@everyone", "@bot", *(r.name for r in roles)}

    owner_names = {r.name for r in roles if r.owner}

    def check_targets(overwrites: list[Overwrite], where: str, stage: bool = False) -> None:
        for o in overwrites:
            if o.target not in valid_targets:
                errors.append(f"{where}: unknown target {o.target}")
            if o.target == "@bot" and o.deny:
                errors.append(f"{where}: the bot may not be denied {', '.join(perms.names_of(o.deny))}")
            # a stage moderator needs Manage Channels on that one stage. Only the owner's roles may have it, only there
            allowed_here = perms.BIT["manage_channels"] if stage and o.target in owner_names else 0
            if _structural(o.allow & ~allowed_here):
                errors.append(f"{where}: an overwrite may not allow {', '.join(_structural(o.allow & ~allowed_here))}")
            if (o.allow | o.deny) & perms.OWNER_ONLY_MASK:
                held = ", ".join(perms.names_of((o.allow | o.deny) & perms.OWNER_ONLY_MASK))
                errors.append(f"{where}: the bot never holds {held}, so no overwrite may name it")

    categories: list[Category] = []
    seen_categories: set[str] = set()
    for entry in raw.get("categories", []):
        name = entry.get("name", "")
        if not name or len(name) > 100:
            errors.append("a category needs a name of 1 to 100 characters")
        if name.lower() in seen_categories:
            errors.append(f"category {name} is listed twice")
        seen_categories.add(name.lower())
        ows = _overwrites(entry.get("overwrites", []), sets, f"category {name}", errors)
        check_targets(ows, f"category {name}")
        categories.append(
            Category(
                name,
                ows,
                bool(entry.get("staff", False)),
                entry.get("enabled", True),
                entry.get("threshold", ""),
                entry.get("threshold_members"),
                list(entry.get("previous_names", [])),
            )
        )

    channels: list[Channel] = []
    seen_channels: set[str] = set()
    for entry in raw.get("channels", []):
        name = entry.get("name", "")
        ctype = entry.get("type", "")
        where = f"channel {name}"
        if ctype not in CHANNEL_TYPES or ctype == "category":
            errors.append(f"{where}: type must be text, announcement, forum, voice or stage")
            continue
        if ctype in ("voice", "stage"):
            if not name or len(name) > 100:
                errors.append(f"{where}: name must be 1 to 100 characters")
        elif not CHANNEL_NAME.match(name) or len(name) > 100:
            errors.append(f"{where}: name must be lower case words joined by hyphens")
        if name in seen_channels:
            errors.append(f"{where} is listed twice")
        seen_channels.add(name)
        parent = entry.get("category")
        if parent is not None and parent.lower() not in seen_categories:
            errors.append(f"{where}: category {parent} is not in the layout")
        topic = entry.get("topic", "")
        if entry.get("topic_file"):
            topic = _read(base / entry["topic_file"], errors, f"{where} topic_file")
        limit = 4096 if ctype == "forum" else 1024
        if len(topic) > limit:
            errors.append(f"{where}: topic is {len(topic)} characters, the limit is {limit}")
        slow = entry.get("slow_mode", 0)
        if not isinstance(slow, int) or not 0 <= slow <= 21600:
            errors.append(f"{where}: slow_mode must be 0 to 21600 seconds")
        forum = entry.get("forum")
        if ctype == "forum":
            forum = _check_forum(forum or {}, where, errors)
        elif forum:
            errors.append(f"{where}: only a forum has forum settings")
        own = _overwrites(entry.get("overwrites", []), sets, where, errors)
        check_targets(own, where, stage=ctype == "stage")
        messages = []
        for file in entry.get("messages", []):
            messages.append(_read(base / file, errors, f"{where} messages"))
        parent_overwrites = []
        parent_is_staff = False
        if parent:
            category = next((c for c in categories if c.name.lower() == parent.lower()), None)
            parent_overwrites = category.overwrites if category else []
            parent_is_staff = bool(category and category.staff)
        channels.append(
            Channel(
                name,
                parent,
                ctype,
                topic,
                slow if isinstance(slow, int) else 0,
                own,
                merge_overwrites(parent_overwrites, own),
                forum,
                messages,
                bool(entry.get("staff", False)) or parent_is_staff,
                entry.get("style", "plain"),
                bool(entry.get("banner", False)),
                bool(entry.get("pin", False)),
                _read(base / entry["read_first"], errors, f"{where} read_first") if entry.get("read_first") else "",
                entry.get("enabled", True),
                entry.get("threshold", ""),
                entry.get("threshold_members"),
                list(entry.get("previous_names", [])),
            )
        )
    per_category: dict[str, int] = {}
    for ch in channels:
        if ch.category:
            per_category[ch.category] = per_category.get(ch.category, 0) + 1
    for cat, count in per_category.items():
        if count > 50:
            errors.append(f"category {cat} holds {count} channels, the limit is 50")

    _give_the_bot_its_row_back(categories, channels, everyone, roles)
    automod = _check_automod(raw.get("automod", []), roles, channels, base, errors)
    layout_so_far = {"roles": roles, "channels": channels}
    onboarding = _check_onboarding(raw.get("onboarding", {}), layout_so_far, everyone, errors)
    webhooks = _check_webhooks(raw.get("webhooks", []), channels, errors)

    for key in ("rules_channel", "public_updates_channel", "safety_alerts_channel", "system_channel"):
        ref = server.get(key)
        if ref and not any(c.name == ref and c.type == "text" and c.enabled for c in channels):
            errors.append(f"server.{key}: {ref} is not an enabled text channel in the layout")
    if not isinstance(server.get("system_channel_flags", 0), int) or server.get("system_channel_flags", 0) not in range(
        64
    ):
        errors.append("server.system_channel_flags must be a whole number from 0 to 63 (six flags, 1 << 0 to 1 << 5)")

    commands = raw.get("commands", {})
    content = None
    if commands.get("content"):
        content_path = base / commands["content"]
        if content_path.is_file():
            try:
                content = tomllib.loads(content_path.read_text(encoding="utf-8"))
            except tomllib.TOMLDecodeError as exc:
                errors.append(f"commands content is not valid TOML: {exc}")

    _check_contact([(ch.name, m) for ch in channels for m in ch.messages], content, server.get("rules_channel"), errors)

    layout = Layout(
        path=path,
        base_dir=base,
        hash8=hash8,
        server=server,
        sets=sets,
        everyone=everyone,
        roles=roles,
        categories=categories,
        channels=channels,
        automod=automod,
        onboarding=onboarding,
        webhooks=webhooks,
        commands=commands,
        commands_content=content,
        status=raw.get("status", {}),
        relay=raw.get("relay", {}),
        brand=raw.get("brand", {}),
    )
    block = commands_block(content)
    for channel in channels:
        if any("{commands}" in m for m in channel.messages):
            if content is None:
                errors.append(f"channel {channel.name}: {{commands}} needs the command content")
            channel.messages = [m.replace("{commands}", block) for m in channel.messages]
    shown = ((content or {}).get("project") or {}).get("commands_channel")
    if shown and not any(c.name == shown for c in channels):
        errors.append(f"project.commands_channel: {shown} is not a channel in the layout")
    _check_messages(layout, errors)
    _check_relay_routes(layout, errors)

    # no identifier of any kind in a layout string. The pattern files are checked for digits only
    # because a pattern for webhook addresses legitimately names the path.
    for label, text in _walk_strings(raw):
        for problem in identifier_problems(text):
            errors.append(f"{label} {problem}")
        if "/api/webhooks/" in text:
            errors.append(f"{label} names a webhook path")
    if errors:
        raise LayoutError(errors)
    return layout


PLACEHOLDER_WORDS = ("example", "placeholder", "changeme", "todo", "your-", "xxx", "test@", "invalid")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def contact_email(commands_content: dict | None) -> str | None:
    """The contact address the worker uses. The rules show the same value, so it is read from one place."""
    return ((commands_content or {}).get("project") or {}).get("contact_email")


def _check_contact(
    layout_texts: list[tuple[str, str]], content: dict | None, rules_channel: str | None, errors: list[str]
) -> None:
    address = contact_email(content)
    uses = [name for name, text in layout_texts if "{contact_email}" in text]
    if not uses:
        return
    if not address or not EMAIL.match(address) or any(w in address.lower() for w in PLACEHOLDER_WORDS):
        errors.append("the contact address in the command content (project.contact_email) is missing or a placeholder")
    if rules_channel and not any(name == rules_channel for name in uses):
        errors.append(f"the rules in {rules_channel} must show the contact address with {{contact_email}}")


def _walk_strings(value, label: str = "layout"):
    if isinstance(value, str):
        yield label, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_strings(item, f"{label}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_strings(item, f"{label}[{index}]")


def _check_forum(forum: dict, where: str, errors: list[str]) -> dict:
    result = {
        "require_tag": bool(forum.get("require_tag", False)),
        "default_sort": forum.get("default_sort", "latest_activity"),
        "layout": forum.get("layout", "list"),
        "post_slow_mode": forum.get("post_slow_mode", 0),
        "reply_slow_mode": forum.get("reply_slow_mode", 0),
        "auto_archive_minutes": forum.get("auto_archive_minutes", 10080),
        "tags": [],
    }
    if result["default_sort"] not in FORUM_SORT:
        errors.append(f"{where}: default_sort must be latest_activity or creation_date")
    if result["layout"] not in FORUM_LAYOUT:
        errors.append(f"{where}: layout must be list or gallery")
    for key in ("post_slow_mode", "reply_slow_mode"):
        if not isinstance(result[key], int) or not 0 <= result[key] <= 21600:
            errors.append(f"{where}: {key} must be 0 to 21600 seconds")
    if result["auto_archive_minutes"] not in AUTO_ARCHIVE:
        errors.append(f"{where}: auto_archive_minutes must be one of {', '.join(map(str, AUTO_ARCHIVE))}")
    tags = forum.get("tags", [])
    if len(tags) > 20:
        errors.append(f"{where}: a forum holds at most 20 tags")
    seen = set()
    for tag in tags:
        tag_name = tag.get("name", "")
        if not tag_name or len(tag_name) > 20:
            errors.append(f"{where}: tag {tag_name!r} must be 1 to 20 characters")
        if tag_name.lower() in seen:
            errors.append(f"{where}: tag {tag_name} is listed twice")
        seen.add(tag_name.lower())
        result["tags"].append({"name": tag_name, "moderated": bool(tag.get("moderated", False))})
    return result


def _check_automod(raw: list[dict], roles: list[Role], channels: list[Channel], base: Path, errors: list[str]):
    result = []
    counts: dict[str, int] = {}
    seen = set()
    role_names = {r.name.lower() for r in roles}
    channel_names = {c.name for c in channels}
    for entry in raw:
        name = entry.get("name", "")
        where = f"auto moderation {name}"
        rule = dict(entry)
        if name.lower() in seen:
            errors.append(f"{where} is listed twice")
        seen.add(name.lower())
        trigger = entry.get("trigger")
        if trigger not in TRIGGERS:
            errors.append(f"{where}: unknown trigger {trigger}")
            continue
        counts[trigger] = counts.get(trigger, 0) + 1
        patterns = list(entry.get("patterns", []))
        if entry.get("patterns_file"):
            file_text = _read(base / entry["patterns_file"], errors, f"{where} patterns_file")
            patterns += [line for line in file_text.splitlines() if line.strip()]
            for line in file_text.splitlines():
                for problem in identifier_problems(line):
                    errors.append(f"{where} pattern file {problem}")
        rule["patterns"] = patterns
        keywords = entry.get("keywords", [])
        if len(patterns) > 10:
            errors.append(f"{where}: at most 10 patterns")
        for pattern in patterns:
            # Discord reads Rust patterns and Python cannot tell whether one compiles there, so what Rust is known
            # to refuse or to blow up is checked by shape
            if len(pattern) > 260:
                errors.append(f"{where}: a pattern is longer than 260 characters")
            for problem in regex_problems(pattern):
                errors.append(f"{where}: pattern {pattern[:30]}... {problem}")
        if len(set(patterns)) != len(patterns):
            errors.append(f"{where}: a pattern is listed twice")
        for word in keywords:
            if len(word) > 60:
                errors.append(f"{where}: keyword {word[:20]} is longer than 60 characters")
        if trigger in ("keyword", "member_profile") and not (keywords or patterns):
            errors.append(f"{where}: needs keywords or patterns")
        if trigger == "keyword_preset":
            for preset in entry.get("presets", []):
                if preset not in PRESETS:
                    errors.append(f"{where}: unknown preset {preset}")
        if trigger == "mention_spam" and not 1 <= entry.get("mention_total_limit", 0) <= 50:
            errors.append(f"{where}: mention_total_limit must be 1 to 50")
        actions = entry.get("actions", [])
        if not actions:
            errors.append(f"{where}: needs at least one action")
        for action in actions:
            kind = action.get("type")
            if kind not in ACTIONS:
                errors.append(f"{where}: unknown action {kind}")
            if kind == "timeout":
                if trigger not in ("keyword", "mention_spam"):
                    errors.append(f"{where}: a timeout works only on keyword and mention spam rules")
                if not 1 <= action.get("seconds", 0) <= 2419200:
                    errors.append(f"{where}: a timeout is 1 second to 28 days")
            if kind == "alert" and action.get("channel") not in channel_names:
                errors.append(f"{where}: alert channel {action.get('channel')} is not in the layout")
            if action.get("message") and len(action["message"]) > 150:
                errors.append(f"{where}: a custom message is at most 150 characters")
        for role in entry.get("exempt_roles", []):
            if role.lower() not in role_names:
                errors.append(f"{where}: exempt role {role} is not in the layout")
        if len(entry.get("exempt_roles", [])) > 20:
            errors.append(f"{where}: at most 20 exempt roles")
        result.append(rule)
    for trigger, count in counts.items():
        if count > TRIGGER_LIMITS[trigger]:
            errors.append(f"auto moderation allows {TRIGGER_LIMITS[trigger]} {trigger} rules, the layout has {count}")
    return result


def _check_onboarding(raw: dict, so_far: dict, everyone: int, errors: list[str]) -> dict:
    if not raw:
        return {}
    channels: list[Channel] = so_far["channels"]
    roles: list[Role] = so_far["roles"]
    by_name = {c.name: c for c in channels}
    role_names = {r.name.lower() for r in roles}
    result = dict(raw)
    mode = raw.get("mode", "default")
    if mode not in ONBOARDING_MODES:
        errors.append("onboarding.mode must be default or advanced")
    defaults = raw.get("default_channels", [])

    def seen_by_everyone(channel: Channel) -> bool:
        row = next((o for o in channel.overwrites if o.target == "@everyone"), None)
        value = perms.channel_permissions(everyone, (row.allow, row.deny) if row else None, [])
        return bool(value & perms.BIT["view_channel"])

    for name in defaults:
        if name not in by_name or not by_name[name].enabled:
            errors.append(f"onboarding: default channel {name} is not an enabled channel in the layout")
        elif by_name[name].type not in ONBOARDING_CHANNEL_TYPES:
            errors.append(
                f"onboarding: default channel {name} is a {by_name[name].type} channel. "
                "Only text, announcement and forum channels can be defaults"
            )
        elif not seen_by_everyone(by_name[name]) or by_name[name].staff:
            errors.append(f"onboarding: default channel {name} is private. Members are opted into defaults")
    if len(set(defaults)) != len(defaults):
        errors.append("onboarding: a default channel is listed twice")
    if raw.get("enabled", False):
        if len(defaults) < 7:
            errors.append("onboarding needs at least 7 default channels")
        postable = 0
        for name in defaults:
            channel = by_name.get(name)
            if channel is None or (channel.type == "forum" and not FORUMS_COUNT_FOR_ONBOARDING):
                continue
            ow = next((o for o in channel.overwrites if o.target == "@everyone"), None)
            allow, deny = (ow.allow, ow.deny) if ow else (0, 0)
            value = perms.channel_permissions(everyone, (allow, deny) if ow else None, [])
            if value & perms.BIT["send_messages"] and value & perms.BIT["view_channel"]:
                postable += 1
        if postable < 5:
            errors.append(f"onboarding needs at least 5 default channels that everyone can post in, found {postable}")
    for prompt in raw.get("prompts", []):
        title = prompt.get("title", "")
        if prompt.get("type") not in PROMPT_TYPES:
            errors.append(f"onboarding question {title}: type must be multiple_choice or dropdown")
        if not title or len(title) > 100:
            errors.append("an onboarding question needs a title of 1 to 100 characters")
        options = prompt.get("options", [])
        if not 1 <= len(options) <= 50:
            errors.append(f"onboarding question {title}: needs 1 to 50 options")
        for option in options:
            if not option.get("title") or len(option["title"]) > 50:
                errors.append(f"onboarding option {option.get('title')}: title must be 1 to 50 characters")
            if len(option.get("description", "")) > 100:
                errors.append(f"onboarding option {option['title']}: description is at most 100 characters")
            for role in option.get("roles", []):
                if role.lower() not in role_names:
                    errors.append(f"onboarding option {option['title']}: role {role} is not in the layout")
            for name in option.get("channels", []):
                if name not in by_name:
                    errors.append(f"onboarding option {option['title']}: channel {name} is not in the layout")
                elif not by_name[name].enabled:
                    errors.append(f"onboarding option {option['title']}: channel {name} is not enabled")
                elif by_name[name].type not in ONBOARDING_CHANNEL_TYPES:
                    errors.append(
                        f"onboarding option {option['title']}: channel {name} must be text, announcement or forum"
                    )
                elif not seen_by_everyone(by_name[name]) or by_name[name].staff:
                    errors.append(
                        f"onboarding option {option['title']}: channel {name} is private, so nobody can be added"
                    )
            # unconfirmed in the specification: whether an option must give a role or a channel
            if not option.get("roles") and not option.get("channels"):
                errors.append(f"onboarding option {option['title']}: give at least one role or channel")
    return result


UNICODE_CLASS = re.compile(r"(?<!\\)(?:\\\\)*\\[wWdDsSbB]")
LOOKAROUND = re.compile(r"\(\?<?[=!]")
BACKREFERENCE = re.compile(r"(?<!\\)(?:\\\\)*\\(?:[1-9]|k<)")
REPEAT = re.compile(r"\{(\d+)(?:,(\d*))?\}")


def regex_problems(pattern: str) -> list[str]:
    """What Discord's Rust regex engine refuses or cannot afford, which Python's cannot tell.

    The documentation says only "Only Rust flavored regex is currently supported" and "Each regex pattern must be 260
    characters or less". Rust has no lookaround and no backreference. In Rust \\w \\d \\s and \\b mean the whole of
    Unicode, so inside a counted repeat they compile to a very large program, which a size limit can refuse. ASCII
    classes such as [A-Za-z0-9_] are written out instead.
    """
    problems = []
    big_repeat = any(int(low) >= 10 or (high and int(high) >= 10) for low, high in REPEAT.findall(pattern))
    if big_repeat and UNICODE_CLASS.search(pattern):
        problems.append(
            "repeats a Unicode class (\\w \\d \\s \\b) many times, which may compile to more than Discord allows. "
            "Write [A-Za-z0-9_] or [0-9] instead"
        )
    if LOOKAROUND.search(pattern):
        problems.append("uses lookaround, which Rust regex does not support")
    if BACKREFERENCE.search(pattern):
        problems.append("uses a backreference, which Rust regex does not support")
    for low, high in REPEAT.findall(pattern):
        if int(low) > 1000 or (high and int(high) > 1000):
            problems.append("repeats more than 1000 times, the Rust limit")
    return problems


def commands_block(content: dict | None) -> str:
    """One linked line for each command a member can use, from the command content and nowhere else."""
    lines = []
    for command in (content or {}).get("commands", []):
        if command.get("staff") or command.get("type", "chat_input") == "message" or not command.get("help"):
            continue
        lines.append(f"- {{command:{command['name']}}} - {command['help']}")
    return "\n".join(lines)


def _check_relay_routes(layout: Layout, errors: list[str]) -> None:
    """A route that posts into a forum must name a tag the forum has, when the forum requires one."""
    for slug, route in layout.relay.get("discussions", {}).items():
        if not isinstance(route, dict) or not route.get("thread"):
            continue
        hook = next((h for h in layout.webhooks if h.get("name") == route.get("webhook")), None)
        channel = layout.channel(hook["channel"]) if hook else None
        where = f"relay route {slug}"
        if channel is None or channel.type != "forum":
            errors.append(f"{where}: thread = true needs a webhook on a forum channel")
            continue
        forum = channel.forum or {}
        if not forum.get("require_tag"):
            continue
        tags = {t["name"].lower() for t in forum.get("tags", [])}
        if str(route.get("tag", "")).lower() not in tags:
            errors.append(f"{where}: {channel.name} requires a tag, so the route needs tag naming one of its tags")
        if not SECRET_NAME.match(str(route.get("tag_secret", ""))):
            errors.append(f"{where}: tag_secret must be an upper case secret name that will hold the tag id")


def _check_webhooks(raw: list[dict], channels: list[Channel], errors: list[str]) -> list[dict]:
    names = {c.name for c in channels}
    seen = set()
    for hook in raw:
        name = hook.get("name", "")
        if not name or len(name) > 80:
            errors.append(f"webhook {name}: name must be 1 to 80 characters")
        if any(word in name.lower() for word in BANNED_WEBHOOK_WORDS):
            errors.append(f"webhook {name}: Discord refuses names that hold discord or clyde")
        if hook.get("channel") not in names:
            errors.append(f"webhook {name}: channel {hook.get('channel')} is not in the layout")
        if not SECRET_NAME.match(hook.get("secret", "")):
            errors.append(f"webhook {name}: secret must be an upper case name")
        if hook.get("store") not in ("github", "cloudflare"):
            errors.append(f"webhook {name}: store must be github or cloudflare")
        key = (hook.get("channel"), name.lower())
        if key in seen:
            errors.append(f"webhook {name} is listed twice")
        seen.add(key)
    return list(raw)


def style_errors(layout: Layout) -> list[str]:
    errors = []
    for label, text in layout.lines_to_check():
        for problem in style_problems(text):
            errors.append(f"{label} {problem}")
    return errors


def _give_the_bot_its_row_back(
    categories: list[Category], channels: list[Channel], everyone: int, roles: list[Role]
) -> None:
    """Make the bot's row on each category hold every bit that any row below it names.

    The channel pages say "Only permissions your bot has in the guild or parent channel (if applicable) can
    be allowed/denied". A category that denies something to everyone takes it from the bot as well and then
    a channel in the category cannot be given a row that names it. So the bot's row on the category allows
    back whatever its channels or the category itself deny. The bits are computed here and never listed.
    """
    held_by_bot = perms.required_for_bot([everyone, *(r.permissions for r in roles if not r.owner)])
    for category in categories:
        for o in category.overwrites:
            held_by_bot |= o.allow | o.deny
    for channel in channels:
        for o in channel.own_overwrites:
            held_by_bot |= o.allow | o.deny
    held_by_bot &= ~perms.OWNER_ONLY_MASK
    for category in categories:
        needed = 0
        for o in category.overwrites:
            needed |= o.allow | o.deny
        for channel in channels:
            if channel.category and channel.category.lower() == category.name.lower():
                for o in channel.own_overwrites:
                    needed |= o.allow | o.deny
        if not needed:
            continue
        rows = {o.target: o for o in category.overwrites}
        everyone_row = rows.get("@everyone")
        bot_row = rows.get("@bot")
        have = perms.channel_permissions(
            perms.base_permissions(everyone, [held_by_bot]),
            (everyone_row.allow, everyone_row.deny) if everyone_row else None,
            [(bot_row.allow, bot_row.deny)] if bot_row else [],
        )
        # view Channel and the rest of the implicit rules are not touched: only whole bits are given back
        missing = needed & held_by_bot & ~have
        if not missing:
            continue
        if bot_row is None:
            bot_row = Overwrite("@bot")
            category.overwrites.append(bot_row)
        bot_row.allow |= missing
    for channel in channels:
        parent = next((c for c in categories if channel.category and c.name.lower() == channel.category.lower()), None)
        channel.overwrites = merge_overwrites(parent.overwrites if parent else [], channel.own_overwrites)


LINK = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+)/(?:blob|tree)/[\w.-]+/([^\s)>\"'\]]+)")


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def read_first_text(layout: Layout, channel: Channel) -> str:
    """The text of a forum's Read first post: the file with the guidelines and the FAQ filled in.

    The FAQ comes from the [[faq]] entries of the command content, so there is one source for it.
    """
    entries = (layout.commands_content or {}).get("faq", [])
    lines = []
    for entry in entries:
        links = " ".join(f"[{link['label']}]({link['url']})" for link in entry.get("links", []))
        lines.append(f"- **{entry['title']}**: {' '.join(entry.get('lines', []))} {links}".rstrip())
    return channel.read_first.replace("{guidelines}", channel.topic).replace("{faq}", "\n".join(lines))


def link_problems(layout: Layout) -> list[str]:
    """Every file of this repository that a member-facing text links to must exist.

    Only possible inside the monorepo, where the files are. In a published copy there is nothing to look at.
    """
    root = layout.base_dir.parent
    if layout.base_dir.name != "discord" or not (root / ".git").exists():
        return []
    repository = layout.relay.get("repository")
    texts = [layout.server.get("description", "")]
    for channel in layout.channels:
        texts += [channel.topic, *channel.messages]
    texts += list(_strings(layout.commands_content or {}))
    missing = []
    for text in texts:
        for repo, target in LINK.findall(text):
            target = re.split(r"[#?]", target)[0].rstrip(".,;:")
            if repo == repository and target and not (root / target).exists():
                missing.append(f"a text links to {target}, which is not in the repository")
    return sorted(set(missing))


READ_FIRST_TAG = "Read first"
IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".webp", ".gif")
UPLOAD_LIMIT = 25 * 1024 * 1024
EMBED_TITLE, EMBED_DESCRIPTION, EMBED_TOTAL = 256, 4096, 6000
STYLES = ("plain", "embed")


def _png_size(data: bytes) -> tuple[int, int] | None:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _check_messages(layout: Layout, errors: list[str]) -> None:
    """Every link must name something in the layout and every message must fit Discord's limits.

    From the message page: an embed title is 256 characters, a description 4096 and all the text of the
    embeds on one message together 6000. A plain message is 2000.
    """
    contact = contact_email(layout.commands_content) or ""
    role_names = {r.name.lower() for r in layout.roles}
    channel_names = {c.name for c in layout.channels}
    registered = {
        c["name"].lower()
        for c in (layout.commands_content or {}).get("commands", [])
        if c.get("type", "chat_input") != "message"
    }
    uses_embed = False
    for channel in layout.channels:
        where = f"channel {channel.name}"
        if channel.style not in STYLES:
            errors.append(f"{where}: style must be plain or embed")
            continue
        if (channel.banner or channel.pin or channel.style == "embed") and not channel.messages:
            errors.append(f"{where}: style, banner and pin apply to managed messages and this channel has none")
        for index, text in enumerate(channel.messages, 1):
            label = f"{where} message {index}"
            for kind, name in textfmt.refs(text):
                if kind == "channel" and name not in channel_names:
                    errors.append(f"{label}: {{channel:{name}}} is not a channel in the layout")
                if kind == "role" and name.lower() not in role_names:
                    errors.append(f"{label}: {{role:{name}}} is not a role in the layout")
                if kind == "command":
                    if layout.commands_content is None:
                        errors.append(f"{label}: {{command:{name}}} needs the command content file")
                    elif name.split(" ")[0].lower() not in registered:
                        errors.append(f"{label}: {{command:{name}}} is not a command in the command content")
            for ref in re.findall(r"\{nav:([a-z]+)\}", text):
                if ref != "customize":
                    errors.append(f"{label}: unknown link {{nav:{ref}}}")
            if channel.style == "embed":
                uses_embed = True
                title, description = textfmt.split_embed(text)
                t, d = textfmt.widest(title, contact), textfmt.widest(description, contact)
                if not title:
                    errors.append(f"{label}: the first line is the title of the embed and it is empty")
                if t > EMBED_TITLE:
                    errors.append(f"{label}: the title is up to {t} characters, the embed limit is {EMBED_TITLE}")
                if d > EMBED_DESCRIPTION:
                    errors.append(
                        f"{label}: the description is up to {d} characters, the embed limit is {EMBED_DESCRIPTION}"
                    )
                if t + d > EMBED_TOTAL:
                    errors.append(f"{label}: the embed text is up to {t + d} characters, the limit is {EMBED_TOTAL}")
            elif textfmt.widest(text, contact) > MESSAGE_LIMIT:
                errors.append(
                    f"{label}: up to {textfmt.widest(text, contact)} characters, the limit is {MESSAGE_LIMIT}"
                )
    for channel in layout.channels:
        if not channel.read_first:
            continue
        where = f"channel {channel.name}"
        if channel.type != "forum":
            errors.append(f"{where}: read_first is for a forum")
            continue
        if not any(t["name"] == READ_FIRST_TAG for t in (channel.forum or {}).get("tags", [])):
            errors.append(f'{where}: a forum with read_first needs a tag named "{READ_FIRST_TAG}"')
        title, description = textfmt.split_embed(read_first_text(layout, channel))
        t, d = textfmt.widest(title, contact), textfmt.widest(description, contact)
        if not title or t > 100:
            errors.append(f"{where}: the first line of the read first text is the post name and is 1 to 100 characters")
        if d > EMBED_DESCRIPTION or t + d > EMBED_TOTAL:
            errors.append(
                f"{where}: the read first text is up to {d} characters, the embed limit is {EMBED_DESCRIPTION}"
            )
        for kind, name in textfmt.refs(description):
            known = {"channel": name in channel_names, "role": name.lower() in role_names}.get(
                kind, name.split(" ")[0].lower() in registered
            )
            if not known:
                errors.append(f"{where}: {{{kind}:{name}}} in the read first text is not in the layout")
    brand = layout.brand
    if uses_embed or any(c.banner for c in layout.channels):
        colour = brand.get("colour")
        if not isinstance(colour, int) or not 0 <= colour <= 0xFFFFFF:
            errors.append("brand.colour must be a number from 0 to 16777215 for embed messages")
        total = 0
        for key in ("logo", "banner"):
            name = brand.get(key)
            if key == "banner" and not any(c.banner for c in layout.channels):
                continue
            if not name:
                errors.append(f"brand.{key} names the image file for embed messages")
                continue
            alt = brand.get(f"{key}_alt", "")
            if not isinstance(alt, str) or not 1 <= len(alt) <= 1024:
                errors.append(f"brand.{key}_alt is the alt text of the {key} image, 1 to 1024 characters")
            file = layout.base_dir / name
            if file.suffix.lower() not in IMAGE_TYPES:
                errors.append(f"brand.{key}: only {', '.join(IMAGE_TYPES)} may be uploaded")
            if not file.is_file():
                errors.append(f"brand.{key}: file {name} not found")
                continue
            data = file.read_bytes()
            total += len(data)
            size = _png_size(data) if file.suffix.lower() == ".png" else None
            if key == "banner" and size and not 1.8 <= size[0] / size[1] <= 2.2:
                errors.append(f"brand.banner is {size[0]} by {size[1]}. Discord shows a banner best near 2 to 1")
        if total > UPLOAD_LIMIT:
            errors.append("the images of one message may not pass 25 MiB together")
