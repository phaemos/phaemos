"""The commands that are not plan or apply: invite link, lockdown, purge, secrets and content export."""

from __future__ import annotations

import subprocess
import urllib.parse
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from serverkit import commandset
from serverkit.access import STAFF_ROLES, perms
from serverkit.engine import Ctx, Options
from serverkit.http import ApiError, AuthError, Client
from serverkit.layout import Layout
from serverkit.state import SetupError, find_guild, load_snapshot, text_channel

SCOPES = "bot applications.commands"
GITHUB_ENVIRONMENT = "community"
EXPORT_PATH = Path("worker") / "src" / "content.generated.json"
PUBLIC_KEY_SECRET = "DISCORD_PUBLIC_KEY"
MAX_LOCKDOWN_HOURS = 24


def invite_url(layout: Layout, application_id: str, staff_setup: bool = True) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": application_id,
            "scope": SCOPES,
            "permissions": layout.bot_permissions(staff_setup=staff_setup),
        },
        quote_via=urllib.parse.quote,
    )
    return f"https://discord.com/oauth2/authorize?{query}"


def lockdown(client: Client, layout: Layout, guild_id: str | None, hours: float, lift: bool) -> str:
    if not lift and not 0 < hours <= MAX_LOCKDOWN_HOURS:
        raise SetupError(f"--hours must be more than 0 and at most {MAX_LOCKDOWN_HOURS}")
    guild = find_guild(client, layout.name, guild_id)
    until = None if lift else (datetime.now(UTC) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    body = {"invites_disabled_until": until, "dms_disabled_until": until}
    what = "lift the lockdown" if lift else f"pause invites and direct messages for {hours:g} hours"
    client.request(
        "PUT", f"/guilds/{guild['id']}/incident-actions", body, reason=f"{layout.name} layout {layout.hash8}: {what}"
    )
    return (
        "Invites and direct messages are open again."
        if lift
        else f"Invites and direct messages are paused for {hours:g} hours."
    )


def parse_age(text: str) -> timedelta:
    if len(text) < 2 or text[-1] not in "dh" or not text[:-1].isdigit() or int(text[:-1]) < 1:
        raise SetupError('--older-than is a number of days or hours such as "365d" or "48h"')
    number = int(text[:-1])
    return timedelta(days=number) if text[-1] == "d" else timedelta(hours=number)


def _when(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _old_messages(client: Client, channel_id: str, age: timedelta, now: datetime) -> tuple[list[dict], bool]:
    """The messages of a channel or thread older than the period and whether any message is newer."""
    old: list[dict] = []
    newer = False
    before = None
    while True:
        path = f"/channels/{channel_id}/messages?limit=100" + (f"&before={before}" if before else "")
        batch = client.request("GET", path)
        if not batch:
            break
        for message in batch:
            if now - _when(message["timestamp"]) > age:
                old.append(message)
            else:
                newer = True
        before = batch[-1]["id"]
        if len(batch) < 100:
            break
    return old, newer


def threads_of(client: Client, guild_id: str, channel_id: str) -> list[dict]:
    """Every active and archived thread of a channel. Staff handle reports in these."""
    found = {}
    active = client.request("GET", f"/guilds/{guild_id}/threads/active")
    for thread in active.get("threads", []):
        if thread.get("parent_id") == channel_id:
            found[thread["id"]] = thread
    for kind in ("public", "private"):
        before = None
        while True:
            path = f"/channels/{channel_id}/threads/archived/{kind}?limit=100" + (f"&before={before}" if before else "")
            page = client.request("GET", path)
            for thread in page.get("threads", []):
                found[thread["id"]] = thread
            threads = page.get("threads", [])
            if not page.get("has_more") or not threads:
                break
            before = threads[-1]["thread_metadata"]["archive_timestamp"]
    return list(found.values())


def purge_candidates(client: Client, ctx: Ctx, channels: list[str], age: timedelta, now: datetime) -> list[dict]:
    """Old messages in the named channels and in their threads and threads whose every message is old."""
    found: list[dict] = []
    for name in channels:
        channel = text_channel(ctx.snap.channels, name)
        if channel is None:
            continue
        old, _ = _old_messages(client, channel["id"], age, now)
        found += [{"kind": "message", "channel": name, "parent": channel["id"], "id": m["id"]} for m in old]
        for thread in threads_of(client, ctx.gid, channel["id"]):
            meta = thread.get("thread_metadata") or {}
            started = meta.get("create_timestamp") or meta.get("archive_timestamp")
            # a thread younger than the retention period stays, whatever it holds
            if started and now - _when(started) <= age:
                continue
            old, newer = _old_messages(client, thread["id"], age, now)
            if not newer:
                found.append({"kind": "thread", "channel": name, "parent": thread["id"], "id": thread["id"]})
            else:
                found += [
                    {
                        "kind": "message",
                        "channel": name,
                        "parent": thread["id"],
                        "id": m["id"],
                        "archived": bool(meta.get("archived")),
                    }
                    for m in old
                ]
    return found


def purge(client: Client, ctx: Ctx, candidates: list[dict]) -> tuple[int, list[str]]:
    """Delete what was found. A refusal for one item is noted and the rest carry on.

    The documentation calls archived threads "generally immutable", so deleting a message inside one may be
    refused. That item is skipped and reported.
    """
    done = 0
    skipped: list[str] = []
    for item in candidates:
        try:
            if item["kind"] == "thread":
                ctx.write("DELETE", f"/channels/{item['id']}", None, "purge old threads")
            else:
                ctx.write("DELETE", f"/channels/{item['parent']}/messages/{item['id']}", None, "purge old entries")
        except AuthError:
            raise
        except ApiError as err:
            where = "a message in an archived thread" if item.get("archived") else f"a {item['kind']}"
            skipped.append(f"{where} in #{item['channel']}: Discord answered {err.status} ({err.message})")
            continue
        done += 1
    return done, skipped


def make_snapshot_ctx(client: Client, layout: Layout, guild_id: str | None) -> Ctx:
    snap = load_snapshot(client, layout.name, guild_id)
    ctx = Ctx(layout, snap, client, Options())
    for c in snap.channels:
        if text_channel([c], c["name"]):
            ctx.channel_ids.setdefault(c["name"], c["id"])
    return ctx


Runner = Callable[[list[str], str], None]


def default_runner(command: list[str], value: str) -> None:
    """Runs an owner tool with the value on standard input so it never appears in a process list."""
    try:
        subprocess.run(command, input=value, text=True, check=True, capture_output=True)  # noqa: S603
    except subprocess.CalledProcessError as exc:
        # keep what the tool said, with the value taken out, so a failure can be diagnosed
        said = ((exc.stderr or "") + (exc.stdout or "")).replace(value, "[removed]").strip()
        raise subprocess.CalledProcessError(exc.returncode, exc.cmd, output=said, stderr=said) from None


STAFF_ROLE_SECRET = "STAFF_ROLE_IDS"
TICKETS_SECRET = "TICKETS_WEBHOOK_URL"
TICKET_TAGS_SECRET = "TICKET_TAG_IDS"


def sync_stored_values(
    client: Client, layout: Layout, guild_id: str | None, runner: Runner = default_runner
) -> list[str]:
    """Reads each webhook address, the public key and the staff role ids and stores them under secret names.

    Everything is read and checked first, so a missing webhook or role stops the run before anything is stored.
    """
    snap = load_snapshot(client, layout.name, guild_id)
    repo = layout.relay.get("repository")
    worker_dir = str(layout.base_dir / "worker")
    jobs: list[tuple[str, str, str, str]] = []
    skipped: list[str] = []
    for hook in layout.webhooks:
        waiting = layout.channel(hook["channel"])
        if waiting is None or not layout.channel_active(waiting):
            # a channel that waits has no webhook yet, so there is no address to store
            skipped.append(f"{hook['secret']} (the channel waits)")
            continue
        channel = text_channel(snap.channels, hook["channel"])
        match = next(
            (
                w
                for w in snap.webhooks
                if channel
                and w["channel_id"] == channel["id"]
                and w["name"].lower() == hook["name"].lower()
                and w.get("application_id") == snap.app["id"]
            ),
            None,
        )
        if match is None:
            raise SetupError(f'the webhook "{hook["name"]}" does not exist yet. Run "serverkit apply" first')
        address = match.get("url") or f"https://discord.com/api/webhooks/{match['id']}/{match['token']}"
        jobs.append((hook["store"], hook["secret"], address, f"{hook['secret']} ({hook['store']})"))
    key = snap.app.get("verify_key")
    if not key:
        raise SetupError("the application did not report its public key")
    jobs.append(("cloudflare", PUBLIC_KEY_SECRET, key, f"{PUBLIC_KEY_SECRET} (cloudflare)"))
    # staff are known to the worker by role. The names come from the layout and the ids from the server now
    ids = []
    found = []
    for name in STAFF_ROLES:
        if layout.role(name) is None:
            continue
        role = next((r for r in snap.roles if not r.get("managed") and r["name"].lower() == name.lower()), None)
        if role is None:
            raise SetupError(
                f'the role "{name}" does not exist on the server yet. Run "serverkit apply" first. Nothing was stored'
            )
        ids.append(role["id"])
        found.append(name)
    if ids:
        label = f"{STAFF_ROLE_SECRET} (cloudflare): {len(ids)} roles, {' and '.join(found)}"
        jobs.append(("cloudflare", STAFF_ROLE_SECRET, ",".join(ids), label))
    # the worker names a ticket's forum tag by id. The ids are looked up by tag name now and travel on standard input
    if any(h["secret"] == TICKETS_SECRET for h in layout.webhooks):
        hook = next(h for h in layout.webhooks if h["secret"] == TICKETS_SECRET)
        forum = text_channel(snap.channels, hook["channel"])
        kinds = (layout.commands_content or {}).get("ticket_kinds", [])
        tags = {t["name"].lower(): t["id"] for t in (forum or {}).get("available_tags", [])}
        pairs = [f"{k['key']}:{tags[k['title'].lower()]}" for k in kinds if k["title"].lower() in tags]
        if pairs:
            jobs.append(
                (
                    "cloudflare",
                    TICKET_TAGS_SECRET,
                    ",".join(pairs),
                    f"{TICKET_TAGS_SECRET} (cloudflare): {len(pairs)} tags",
                )
            )
    # a forum that requires a tag refuses a relay post without one, so the relay is given the id of the tag it uses
    discussions = layout.relay.get("discussions", {})
    for slug, route in discussions.items():
        if not (isinstance(route, dict) and route.get("tag_secret")):
            continue
        hook = next((h for h in layout.webhooks if h["name"] == route.get("webhook")), None)
        forum = text_channel(snap.channels, hook["channel"]) if hook else None
        tag = next(
            (t for t in (forum or {}).get("available_tags", []) if t["name"].lower() == str(route.get("tag")).lower()),
            None,
        )
        if tag is None:
            raise SetupError(
                f'the forum tag "{route.get("tag")}" for the {slug} discussions does not exist yet. '
                'Run "serverkit apply" first'
            )
        jobs.append(("github", route["tag_secret"], tag["id"], f"{route['tag_secret']} (github)"))
    stored = []
    for store, name, value, label in jobs:
        _store(runner, store, name, value, repo, worker_dir)
        stored.append(label)
    return stored + [f"skipped {item}" for item in skipped]


def _store(runner: Runner, store: str, name: str, value: str, repo: str | None, worker_dir: str) -> None:
    if store == "github":
        if not repo:
            raise SetupError("the layout has no [relay] repository, so there is nowhere to store a GitHub secret")
        command = ["gh", "secret", "set", name, "--env", GITHUB_ENVIRONMENT, "--repo", repo]
    else:
        command = [
            "npx",
            "--prefix",
            worker_dir,
            "wrangler",
            "secret",
            "put",
            name,
            "--config",
            str(Path(worker_dir) / "wrangler.toml"),
        ]
    try:
        runner(command, value)
    except subprocess.CalledProcessError as exc:
        said = (exc.stderr or "").replace(value, "[removed]").strip()[:600]
        raise SetupError(f"could not store {name} with {command[0]} (exit {exc.returncode}): {said}") from None
    except OSError as exc:
        raise SetupError(f"could not run {command[0]} to store {name}: {exc.strerror or type(exc).__name__}") from None


def export_content(layout: Layout, check: bool) -> tuple[bool, str]:
    """Write the worker's JSON. With check, report whether the file on disk is current."""
    if layout.commands_content is None:
        raise SetupError("the layout names no command content file or it is missing")
    target = layout.base_dir / EXPORT_PATH
    text = commandset.export_json(layout.commands_content)
    if check:
        current = target.read_text(encoding="utf-8") if target.is_file() else ""
        return current == text, str(EXPORT_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return True, str(EXPORT_PATH)


def role_state(layout: Layout, role: dict | None) -> tuple[str, int, int]:
    """Whether the bot's role is raised, lowered or partly raised, with the permissions held and needed."""
    needed = layout.bot_permissions()
    if role is None:
        return "not found", 0, len(perms.names_of(needed))
    held = len(perms.names_of(int(role["permissions"]) & needed))
    total = len(perms.names_of(needed))
    return ("raised" if held == total else "lowered" if not held else "partly raised"), held, total


def stand_down(layout: Layout, role: dict | None, raising: bool) -> list[str]:
    """Steps for the owner to lower the bot's role to nothing between layout changes or raise it again.

    A bot "can edit roles of a lower position than its highest role", so it cannot lower its own role
    and this is by hand.
    """
    needed = perms.names_of(layout.bot_permissions())
    lines = []
    if role is not None:
        held = perms.names_of(int(role["permissions"]) & layout.bot_permissions())
        state = "raised" if len(held) == len(needed) else "lowered" if not held else "partly raised"
        lines.append(f"The bot's role holds {len(held)} of the {len(needed)} permissions the layout needs ({state}).")
    if raising:
        lines += [
            "To raise it before a layout change:",
            "1. Open Server Settings, then Roles, then the bot's role (named after the application).",
            f"2. Open Permissions and switch on exactly these {len(needed)}: {', '.join(needed)}.",
            "3. Press Save changes.",
        ]
    else:
        lines += [
            "To lower it until the next layout change:",
            "1. Open Server Settings, then Roles, then the bot's role (named after the application).",
            "2. Open Permissions and switch off every permission. The role stays and holds nothing.",
            "3. Press Save changes.",
        ]
    lines.append(
        "The bot cannot do this itself: Discord only lets a bot edit roles below its own highest role, "
        "so it cannot lower its own. Slash commands and the GitHub relay do not use the bot's permissions "
        "and keep working while it is lowered."
    )
    return lines


# names as Discord's role settings screen shows them, for what the owner switches on by hand
SCREEN_NAMES = {
    "kick_members": "Kick, Approve, and Reject Members",
    "ban_members": "Ban Members",
    "mention_everyone": "Mention @everyone, @here, and All Roles",
}


def screen_name(name: str) -> str:
    return SCREEN_NAMES.get(name, name.replace("_", " ").title())


def staff_roles(client: Client, layout: Layout, guild_id: str | None, apply: bool) -> tuple[list[str], list[str]]:
    """Set the owner's roles up once, from the layout, then leave them to the owner.

    A role is made or filled in while it sits below the bot's highest role, with the layout's permissions
    intersected with what the bot holds, since Discord refuses anything else. A role at or above the bot is the
    finished state and is left alone. No member is given a role and no role is moved, renamed or deleted.
    Returns the lines that say what was or would be done and the numbered list for the owner.
    """
    me = client.request("GET", "/users/@me")
    guild = find_guild(client, layout.name, guild_id)
    gid = guild["id"]
    roles = client.request("GET", f"/guilds/{gid}/roles")
    member = client.request("GET", f"/guilds/{gid}/members/{me['id']}")
    bot_roles = [r for r in roles if r["id"] in member.get("roles", [])]
    if not bot_roles:
        raise SetupError('the bot\'s own role was not found. Invite the bot again with "serverkit invite-url"')
    held = int(next(r for r in roles if r["id"] == gid)["permissions"])
    for role in bot_roles:
        held |= int(role["permissions"])
    if held & perms.BIT["administrator"]:
        raise SetupError("the bot holds Administrator. This tool never runs with it")
    if not held & perms.BIT["manage_roles"]:
        raise SetupError("the bot does not hold Manage Roles, which setting a role up needs")
    top = max(r["position"] for r in bot_roles)
    reason = f"{layout.name} layout {layout.hash8}"
    lines: list[str] = []
    by_hand: list[tuple[str, list[str]]] = []
    for want in (r for r in layout.roles if r.owner):
        # kick, ban and mention everyone are never set by the bot, whatever it happens to hold
        settable = want.permissions & held & ~perms.OWNER_ONLY_MASK
        existing = next((r for r in roles if not r.get("managed") and r["name"].lower() == want.name.lower()), None)
        label = f'role "{want.name}"'
        if existing is None:
            by_hand.append((want.name, perms.names_of(want.permissions & ~settable)))
            lines.append(f"create     {label} with {len(perms.names_of(settable))} permissions")
            if apply:
                client.request(
                    "POST",
                    f"/guilds/{gid}/roles",
                    {
                        "name": want.name,
                        "permissions": str(settable),
                        "color": want.colour,
                        "hoist": want.hoist,
                        "mentionable": want.mentionable,
                    },
                    reason=f"{reason}: set up the {want.name} role",
                )
            continue
        if existing["position"] >= top:
            lines.append(f"leave      {label} sits at or above the bot's role. That is the finished state")
            continue
        # keep what the owner already switched on by hand and the layout wants, such as kick or ban
        target = settable | (int(existing["permissions"]) & want.permissions & (perms.OWNER_ONLY_MASK | ~held))
        by_hand.append((want.name, perms.names_of(want.permissions & ~target)))
        differs = (
            int(existing["permissions"]) != target
            or bool(existing.get("hoist")) != want.hoist
            or bool(existing.get("mentionable")) != want.mentionable
            or int(existing.get("color", 0)) != want.colour
        )
        if not differs:
            lines.append(f"ok         {label} already matches")
            continue
        lines.append(f"update     {label}: set permissions, colour, hoist and mentionable from the layout")
        if apply:
            client.request(
                "PATCH",
                f"/guilds/{gid}/roles/{existing['id']}",
                {
                    "permissions": str(target),
                    "color": want.colour,
                    "hoist": want.hoist,
                    "mentionable": want.mentionable,
                },
                reason=f"{reason}: set up the {want.name} role",
            )
    names = " and ".join(r.name for r in layout.roles if r.owner)
    steps = [
        f"Drag {names} above the bot's role NOW (Server Settings, Roles). Until this is done, anyone holding the "
        "bot's token could edit them.",
    ]
    missing = [(n, [screen_name(x) for x in ns]) for n, ns in by_hand if ns]
    if missing:
        listed = "; ".join(f"{n}: {', '.join(ns)}" for n, ns in missing)
        steps.append(f"Switch on by hand the permissions the bot could not set. {listed}.")
    steps.append("Give yourself Maintainer.")
    steps.append('Run "python3 -m serverkit plan --layout <your layout file>".')
    return lines, steps
