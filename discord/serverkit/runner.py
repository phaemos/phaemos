"""Orchestration: preflight, the plan, the confirmation, the run and the exit codes."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from serverkit import perms
from serverkit.engine import (
    SECTIONS,
    STEPS,
    Blocked,
    Change,
    Ctx,
    Lockout,
    plan_application,
    plan_automod,
    plan_channels,
    plan_commands,
    plan_messages,
    plan_onboarding,
    plan_pins,
    plan_pointers,
    plan_readfirst,
    plan_roles,
    plan_settings,
    plan_webhooks,
)
from serverkit.http import ApiError, AuthError, Fatal
from serverkit.state import SUPPRESS_EMBEDS, SetupError, text_channel

EXIT_OK, EXIT_ERROR, EXIT_SETUP, EXIT_BLOCKED, EXIT_PENDING = 0, 1, 2, 3, 4
PENDING_WORDS = {"create", "update", "delete", "rename", "rotate"}
COLOURS = {
    "create": "32",
    "update": "33",
    "delete": "31",
    "rename": "33",
    "rotate": "33",
    "blocked": "31",
    "error": "31",
    "warning": "35",
    "ok": "32",
}
RESET_TOKEN = (
    "Closing the session, in order. The bot's role is strong and its token stays valid until it is reset:",
    '1. Lower the bot\'s role by hand. Run "python3 -m serverkit stand-down" for the steps.',
    '2. Check it. Run "python3 -m serverkit session-check". It says plainly whether the role is still raised.',
    "3. Reset the bot token. Open https://discord.com/developers/applications, choose the application, open Bot "
    "and press Reset Token. The old token stops working at once. Store the new one only when you next need it.",
)

# the permission the documentation names for each kind of route, for the message after a refusal
ROUTE_PERMISSION = (
    ("/webhooks", "manage_webhooks"),
    ("/messages/pins", "pin_messages"),
    ("/threads", "manage_threads"),
    ("/messages", "send_messages and read_message_history"),
    ("/roles", "manage_roles"),
    ("/auto-moderation", "manage_guild"),
    ("/onboarding", "manage_guild and manage_roles"),
    ("/incident-actions", "manage_guild"),
    ("/channels", "manage_channels"),
    ("/guilds/:id", "manage_guild"),
)


class Out:
    """Output that can never carry the token or a webhook address."""

    def __init__(self, stdout, stderr, secrets: list[str] | None = None, colour: bool = False):
        self.stdout = stdout
        self.stderr = stderr
        self.secrets = [s for s in (secrets or []) if s]
        self.colour = colour

    def clean(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, "[removed]")
        return text

    def line(self, text: str = "") -> None:
        self.stdout.write(self.clean(text) + "\n")

    def error(self, text: str) -> None:
        self.stderr.write(self.clean(text) + "\n")

    def word(self, word: str, text: str) -> str:
        padded = f"{word:<10}"
        if self.colour and word in COLOURS:
            padded = f"\x1b[{COLOURS[word]}m{padded}\x1b[0m"
        return f"  {padded} {text}"


@dataclass
class Plan:
    preflight: list[Change]
    changes: list[Change]
    owner_steps: list[str] = field(default_factory=list)

    def count(self, word: str) -> int:
        return sum(1 for c in self.changes if c.word == word)

    @property
    def held(self) -> int:
        return sum(1 for c in self.changes if c.held)

    @property
    def blocked(self) -> int:
        return self.count("blocked") + self.held + sum(1 for c in self.preflight if c.word == "blocked")

    @property
    def pending(self) -> bool:
        return any(c.word in PENDING_WORDS and not c.held for c in self.changes)


def preflight(ctx: Ctx) -> tuple[list[Change], list[str]]:
    """Read only checks of the bot itself. The second list holds what stops the run."""
    lines: list[Change] = []
    errors: list[str] = []
    snap = ctx.snap
    member = ctx.client.request("GET", f"/guilds/{ctx.gid}/members/{ctx.bot_id}")
    bot_roles = [r for r in snap.roles if r["id"] in member.get("roles", [])]
    if snap.bot_role is None:
        errors.append(
            'the bot\'s own role was not found. Invite the bot again with the link from "serverkit invite-url"'
        )
        return lines, errors
    if snap.bot_role not in bot_roles:
        bot_roles.append(snap.bot_role)
    held = 0
    for role in bot_roles:
        held |= int(role["permissions"])
        if int(role["permissions"]) & perms.BIT["administrator"]:
            errors.append(
                f"the role {role['name']!r} holds Administrator and the bot holds that role. This tool never runs with "
                "Administrator. Remove it in the server settings, then run this again"
            )
    everyone = snap.role_by_id(ctx.gid)
    held |= int(everyone["permissions"]) if everyone else 0
    needed = ctx.layout.bot_permissions()
    missing = perms.names_of(needed & ~held)
    if missing:
        errors.append(
            f"the bot is missing {len(missing)} permissions the layout needs: {', '.join(missing)}. "
            'If you lowered its role with "serverkit stand-down", run "serverkit stand-down --raise" for the list '
            'to switch back on. Otherwise invite the bot again with the link from "serverkit invite-url" or switch '
            'the missing permissions on by hand in Server Settings, Roles, on the bot\'s role'
        )
    else:
        lines.append(
            Change("preflight", "ok", f"the bot holds all {len(perms.names_of(needed))} permissions the layout needs")
        )
    top = max(r["position"] for r in bot_roles)
    managed = {r.name.lower() for r in ctx.layout.roles if not r.owner}
    owners = {r.name.lower() for r in ctx.layout.roles if r.owner}
    tie_note = (
        "Discord sorts roles with the same position by id and its documentation does not say which way, "
        "so a tie is never relied on"
    )
    above = [
        r["name"]
        for r in snap.roles
        if r["name"].lower() in managed and not r.get("managed") and r["position"] > top and r["id"] != ctx.gid
    ]
    tied = [
        r["name"]
        for r in snap.roles
        if r["name"].lower() in managed and not r.get("managed") and r["position"] == top and r["id"] != ctx.gid
    ]
    over = [
        r["name"]
        for r in snap.roles
        if r["name"].lower() in owners and not r.get("managed") and r["position"] <= top and r["id"] != ctx.gid
    ]
    if above:
        errors.append(
            f"the bot's role is not above {', '.join(above)}. "
            "In Server Settings, Roles, drag the bot's role above them, then run this again"
        )
    if tied:
        lines.append(
            Change(
                "preflight",
                "warning",
                f"{', '.join(tied)} tie with the bot's role. {tie_note}. "
                "A bot cannot move into its own place, so drag them below the bot's role by hand",
            )
        )
    if over:
        tied_over = [r["name"] for r in snap.roles if r["name"] in over and r["position"] == top]
        extra = f" {tie_note}." if tied_over else ""
        errors.append(
            f"the bot's role is not below {', '.join(over)}. Those roles are the owner's.{extra} "
            'If "serverkit staff-roles" has been run, the drag is the step outstanding. In Server Settings, Roles, '
            "drag them above the bot's role (or the bot's role below them), then run this again"
        )
    if not above and not over and not tied:
        lines.append(
            Change("preflight", "ok", "the bot's role is above the roles it manages and below the owner's roles")
        )
    if not snap.community:
        waiting = [c for c in ctx.layout.active_channels if c.type in ("announcement", "stage")]
        lines.append(
            Change(
                "preflight",
                "blocked",
                f"Community is off: {len(waiting)} announcement channels and onboarding wait for it",
                owner_step="Enable Community in the server settings, then run this again.",
            )
        )
    elif (
        ctx.layout.active_channels
        and any(c.type == "announcement" for c in ctx.layout.active_channels)
        and "NEWS" not in snap.features
    ):
        lines.append(
            Change(
                "preflight", "blocked", "Community is on but the NEWS feature is missing, so announcement channels wait"
            )
        )
    return lines, errors


def build_plan(ctx: Ctx, only: set[str] | None) -> Plan:
    chosen = set(STEPS) if only is None else only
    changes: list[Change] = []
    changes += plan_settings(ctx)
    roles = plan_roles(ctx)
    channels = plan_channels(ctx)
    changes += roles if "roles" in chosen else []
    changes += channels if "channels" in chosen else []
    if "pointers" in chosen:
        changes += plan_pointers(ctx)
    if "automod" in chosen:
        changes += plan_automod(ctx)
    if "onboarding" in chosen:
        changes += plan_onboarding(ctx, ctx.unavailable)
    # commands are planned before the messages so that a link to one can be written by id in the same run
    commands = plan_commands(ctx)
    changes += commands if "commands" in chosen else []
    if "messages" in chosen:
        changes += plan_messages(ctx, ctx.unavailable)
    if "readfirst" in chosen:
        changes += plan_readfirst(ctx, ctx.unavailable)
    if "pins" in chosen:
        changes += plan_pins(ctx, ctx.unavailable)
    if "webhooks" in chosen:
        changes += plan_webhooks(ctx, ctx.unavailable)
    if "application" in chosen:
        changes += plan_application(ctx, ctx.opts.interactions_url)
    if only is not None:
        changes = [c for c in changes if c.step in chosen]
    if ctx.problems:
        raise SetupError("\n".join(dict.fromkeys(ctx.problems)))
    order = {name: n for n, name in enumerate(STEPS)}
    changes.sort(key=lambda c: order[c.step])
    owners = []
    for c in changes:
        if c.owner_step and c.owner_step not in owners:
            owners.append(c.owner_step)
    return Plan([], changes, owners)


def summary_line(plan: Plan) -> str:
    parts = []
    counts = [
        ("create", "to create"),
        ("update", "to update"),
        ("delete", "to delete"),
        ("rotate", "to rotate"),
    ]
    for word, label in counts:
        n = plan.count(word)
        if n:
            parts.append(f"{n} {label}")
    renames = [c for c in plan.changes if c.word == "rename"]
    if any(not c.held for c in renames):
        parts.append(f"{sum(1 for c in renames if not c.held)} to rename")
    if plan.held:
        parts.append(f"{plan.held} rename held back")
    for word, label in (
        ("blocked", "blocked"),
        ("unmanaged", "unmanaged"),
        ("deferred", "deferred"),
        ("ready", "ready to switch on"),
    ):
        n = plan.count(word) + (sum(1 for c in plan.preflight if c.word == "blocked") if word == "blocked" else 0)
        if n:
            parts.append(f"{n} {label}")
    warnings = plan.count("warning")
    if warnings:
        parts.append(f"{warnings} warning" + ("s" if warnings != 1 else ""))
    waiting = plan.blocked or plan.pending or any(c.word == "rename" for c in plan.changes)
    if not waiting:
        parts.insert(0, "nothing to change")
    return "Summary: " + ", ".join(parts) + "."


def print_plan(out: Out, plan: Plan, header: str, mode: str, fmt: str, exit_code: int) -> None:
    if fmt == "json":
        data = {
            "header": header,
            "mode": mode,
            "preflight": [{"word": c.word, "text": c.text} for c in plan.preflight],
            "changes": [{"section": SECTIONS[c.step], "word": c.word, "text": c.text} for c in plan.changes],
            "summary": summary_line(plan),
            "owner_steps": plan.owner_steps,
            "exit_code": exit_code,
        }
        out.line(json.dumps(data, indent=2))
        return
    out.line(header)
    if mode == "plan":
        out.line('Mode: plan. Nothing is changed. Run "serverkit apply" to make these changes.')
    else:
        out.line("Mode: apply.")
    out.line()
    if plan.preflight:
        out.line("Preflight")
        for c in plan.preflight:
            out.line(out.word(c.word, c.text))
        out.line()
    seen: list[str] = []
    for c in plan.changes:
        section = SECTIONS[c.step]
        if section not in seen:
            seen.append(section)
    for section in seen:
        out.line(section)
        for c in plan.changes:
            if SECTIONS[c.step] == section:
                out.line(out.word(c.word, c.text))
        out.line()
    out.line(summary_line(plan))
    steps = list(plan.owner_steps)
    for c in plan.preflight:
        if c.owner_step and c.owner_step not in steps:
            steps.insert(0, c.owner_step)
    if steps:
        out.line("Still for the owner to do by hand:")
        for n, step in enumerate(steps, 1):
            out.line(f"  {n}. {step}")


def confirm(out: Out, destructive: list[Change], server_name: str, stdin, isatty) -> bool:
    """Ask for the server's name. Refuses outright when there is no terminal to ask on."""
    if not isatty():
        out.error("This needs a terminal so that you can type the server's name. Nothing was changed.")
        return False
    out.line("These changes remove or rename things and cannot be undone:")
    for c in destructive:
        out.line(out.word(c.word, c.text))
    out.line("Deleting a channel cannot be undone.")
    out.stdout.write(out.clean(f'Type the server name, "{server_name}", to go ahead. Anything else cancels: '))
    out.stdout.flush()
    answer = stdin.readline().rstrip("\n")
    if answer != server_name:
        out.line("Cancelled. Nothing was changed.")
        return False
    return True


def refusal_hint(err: ApiError) -> str:
    if err.status != 403:
        return ""
    if err.method in ("POST", "PATCH", "PUT") and "/channels" in err.route and "/messages" not in err.route:
        return (
            " The documentation says this needs manage_channels and that a bot can only allow or deny permissions "
            "it holds in the server and in the parent channel. Check the bot's row on the category."
        )
    for part, permission in ROUTE_PERMISSION:
        if part in err.route:
            return f" The documentation says this needs {permission}."
    return ""


# A step that needs what an earlier one makes is skipped when that one failed. Every other step carries on, since
# nothing in it reads the failed work: a roles failure does not stop auto moderation of a layout without role
# names, but one that names a role does, so it depends on roles. Messages read channels and roles and pins read
# messages. Commands, settings, the application address and webhooks of channels that exist stand alone.
DEPENDS = {
    "settings": (),
    "roles": (),
    "channels": ("roles",),
    "pointers": ("channels",),
    "automod": ("roles", "channels"),
    "onboarding": ("roles", "channels"),
    "commands": (),
    "messages": ("channels", "roles"),
    "readfirst": ("channels",),
    "pins": ("messages",),
    "webhooks": ("channels",),
    "application": (),
}


@dataclass
class Result:
    applied: list[Change]
    blocked: list[tuple[Change, str]]
    failed: tuple[Change, str] | None
    not_applied: list[Change]
    failures: list[tuple[Change, str]] = field(default_factory=list)
    skipped: list[tuple[Change, str]] = field(default_factory=list)


def execute(ctx: Ctx, plan: Plan) -> Result:
    applied: list[Change] = []
    blocked: list[tuple[Change, str]] = []
    failures: list[tuple[Change, str]] = []
    skipped: list[tuple[Change, str]] = []
    runnable = [c for c in plan.changes if c.run is not None and not c.held]
    done: set[int] = set()
    broken: set[str] = set()
    stop_all = False
    for change in runnable:
        if stop_all:
            break
        lost = [d for d in DEPENDS.get(change.step, ()) if d in broken]
        if lost:
            skipped.append((change, f"it needs {', '.join(lost)}, which did not finish"))
            # what needs this step is skipped as well: nothing runs on top of work that did not happen
            broken.add(change.step)
            done.add(id(change))
            continue
        try:
            change.run()
        except Blocked as exc:
            blocked.append((change, str(exc)))
            done.add(id(change))
            continue
        except Fatal as exc:
            # three refusals in one run: the bot lacks something, so nothing further is tried
            failures.append((change, str(exc)))
            stop_all = True
            break
        except AuthError as exc:
            failures.append((change, f"the token was refused. {exc}"))
            stop_all = True
            break
        except Lockout as exc:
            failures.append((change, str(exc)))
            broken.add(change.step)
            done.add(id(change))
            continue
        except ApiError as exc:
            failures.append((change, f"{exc}.{refusal_hint(exc)}"))
            broken.add(change.step)
            done.add(id(change))
            continue
        done.add(id(change))
        applied.append(change)
    applied_ids = {id(c) for c in applied}
    for c in plan.changes:
        if c.follows is not None and id(c.follows) in applied_ids:
            applied.append(c)
    failed_ids = {id(c) for c, _ in failures}
    not_applied = [c for c in runnable if id(c) not in done or id(c) in failed_ids]
    not_applied += [c for c, _ in skipped]
    return Result(applied, blocked, failures[0] if failures else None, not_applied, failures, skipped)


def summary_text(ctx: Ctx, applied: list[Change]) -> str:
    head = f"{ctx.layout.name} layout {ctx.layout.hash8} applied {len(applied)} changes."
    lines = [head]
    for c in applied:
        # the summary can never hold a live mention, even with mentions switched off
        line = f"{c.word} {c.text}".replace("@everyone", "the everyone role")
        if len("\n".join([*lines, line])) > 1800:
            lines.append(f"Plus {len(applied) - (len(lines) - 1)} more changes.")
            break
        lines.append(line)
    return "\n".join(lines)


def post_summary(ctx: Ctx, applied: list[Change]) -> None:
    name = ctx.layout.server.get("summary_channel", "mod-log")
    channel_id = ctx.cid(name)
    if channel_id is None:
        found = text_channel(ctx.snap.channels, name)
        channel_id = found["id"] if found else None
    if channel_id is None:
        return
    body = {"content": summary_text(ctx, applied), "allowed_mentions": {"parse": []}, "flags": SUPPRESS_EMBEDS}
    ctx.write("POST", f"/channels/{channel_id}/messages", body, "post the run summary")


def decide_exit(plan: Plan, mode: str, result: Result | None) -> int:
    if result is not None and (result.failed or result.failures):
        return EXIT_ERROR
    blocked = plan.blocked + (len(result.blocked) if result else 0)
    if blocked:
        return EXIT_BLOCKED
    if mode == "plan" and plan.pending:
        return EXIT_PENDING
    return EXIT_OK
