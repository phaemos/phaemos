"""The command line. Plan is the default and apply is always asked for by name."""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from serverkit import __version__, commandset, ops, textfmt
from serverkit.access import access_problems
from serverkit.engine import PRUNE_KINDS, STEPS, Change, Ctx, Options
from serverkit.http import ApiError, AuthError, Client, Fatal, resolve_base
from serverkit.layout import Layout, LayoutError, contact_email, link_problems, load, style_errors
from serverkit.runner import (
    EXIT_BLOCKED,
    EXIT_ERROR,
    EXIT_OK,
    EXIT_SETUP,
    RESET_TOKEN,
    Out,
    Plan,
    build_plan,
    confirm,
    decide_exit,
    execute,
    post_summary,
    preflight,
    print_plan,
    refusal_hint,
)
from serverkit.state import SetupError, find_guild, load_snapshot

COMMANDS = (
    "check",
    "plan",
    "apply",
    "invite-url",
    "sync-secrets",
    "export-content",
    "lockdown",
    "purge-mod-log",
    "stand-down",
    "session-check",
    "staff-roles",
    "rules-text",
)


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # noqa: D102
        raise SetupError(f"bad arguments: {message}")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="serverkit", description="Builds a Discord community server from a layout file.")
    parser.add_argument("command", nargs="?", default="plan", choices=COMMANDS)
    parser.add_argument("--layout", help="the layout file. Optional when layout/ holds exactly one")
    parser.add_argument("--only", help="limit the run to these steps, separated by commas")
    parser.add_argument("--allow-renames", action="store_true", help="apply the renames the plan shows")
    parser.add_argument("--prune", action="append", metavar="KIND", help="delete unmanaged objects of one kind")
    parser.add_argument("--rotate-webhook", action="append", metavar="NAME", default=[])
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--colour", action="store_true")
    parser.add_argument("--max-wait", type=float, default=900)
    parser.add_argument("--no-summary", action="store_true")
    parser.add_argument("--hours", type=float)
    parser.add_argument("--lift", action="store_true")
    parser.add_argument("--older-than", default="365d")
    parser.add_argument(
        "--raise", dest="raise_role", action="store_true", help="stand-down: the steps to raise the role again"
    )
    parser.add_argument("--apply", action="store_true", help="staff-roles: make the changes. The default is a dry run")
    parser.add_argument(
        "--no-staff-setup", action="store_true", help="invite-url: ask only for what plan and apply need"
    )
    parser.add_argument("--check", action="store_true", help="export-content: fail when the file is out of date")
    parser.add_argument("--version", action="version", version=f"serverkit {__version__}")
    return parser


def find_layout(path: str | None, cwd: Path) -> Path:
    if path:
        return Path(path)
    found = sorted((cwd / "layout").glob("*.toml"))
    if len(found) != 1:
        raise SetupError("name the layout with --layout. layout/ does not hold exactly one file")
    return found[0]


def load_layout(path: Path) -> Layout:
    try:
        layout = load(path)
    except LayoutError as exc:
        raise SetupError("the layout is not valid:\n  " + "\n  ".join(exc.errors)) from None
    problems = style_errors(layout)
    if problems:
        raise SetupError("the layout breaks the text rules:\n  " + "\n  ".join(problems))
    problems = access_problems(layout)
    if problems:
        raise SetupError("the layout would lock someone out or show a private channel:\n  " + "\n  ".join(problems))
    return layout


def user_agent(layout: Layout) -> str:
    repo = layout.relay.get("repository", "")
    address = f"https://github.com/{repo}" if repo else "https://github.com"
    return f"DiscordBot ({address}, {__version__})"


def main(
    argv: list[str] | None = None,
    *,
    env: dict[str, str] | None = None,
    stdin=None,
    stdout=None,
    stderr=None,
    isatty: Callable[[], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    runner: ops.Runner = ops.default_runner,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    cwd: Path | None = None,
) -> int:
    env = dict(os.environ) if env is None else env
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    isatty = isatty or (lambda: bool(getattr(stdin, "isatty", lambda: False)()))
    token = env.get("DISCORD_BOT_TOKEN", "")
    out = Out(stdout, stderr, [token])
    try:
        args = build_parser().parse_args(argv)
    except SetupError as exc:
        out.error(str(exc))
        return EXIT_SETUP
    except SystemExit as exc:  # --version and --help
        return int(exc.code or 0)
    out.colour = bool(args.colour) and "NO_COLOR" not in env
    try:
        return _dispatch(args, env, out, stdin, isatty, sleep, clock, runner, now, cwd or Path.cwd())
    except SetupError as exc:
        out.error(f"Could not start. {exc}")
        return EXIT_SETUP
    except AuthError:
        out.error(
            "Could not start. Discord refused the token. Check DISCORD_BOT_TOKEN or reset it in the developer portal."
        )
        return EXIT_SETUP
    except ValueError as exc:
        out.error(f"Could not start. {exc}")
        return EXIT_SETUP
    except ApiError as exc:
        out.error(f"Stopped. {exc}.{refusal_hint(exc)}")
        return EXIT_ERROR
    except Fatal as exc:
        out.error(str(exc))
        return EXIT_ERROR


def _dispatch(args, env, out: Out, stdin, isatty, sleep, clock, runner, now, cwd: Path) -> int:
    command = args.command
    layout = load_layout(find_layout(args.layout, cwd))

    if command == "check":
        return _check(layout, out)
    if command == "rules-text":
        return _rules_text(layout, out)
    if command == "export-content":
        ok, path = ops.export_content(layout, args.check)
        if args.check:
            out.line(f"{path} is up to date." if ok else f"{path} is out of date. Run: serverkit export-content")
            return EXIT_OK if ok else EXIT_ERROR
        out.line(f"Wrote {path}.")
        return EXIT_OK

    if command == "stand-down":
        return _stand_down(args, layout, env, out, sleep, clock)
    if command == "session-check":
        return _session_check(layout, env, out, sleep, clock)

    token = env.get("DISCORD_BOT_TOKEN", "")
    if not token:
        raise SetupError("DISCORD_BOT_TOKEN is not set. The README says how to keep it out of files and shell history")
    base = resolve_base(env.get("DISCORD_API_BASE"))
    guild_id = env.get("DISCORD_GUILD_ID") or None
    read_only = command in ("plan", "invite-url", "sync-secrets") or (command == "staff-roles" and not args.apply)
    client = Client(
        base, token, user_agent(layout), max_wait=args.max_wait, read_only=read_only, sleep=sleep, clock=clock
    )

    if command == "invite-url":
        app = client.request("GET", "/applications/@me")
        out.line(ops.invite_url(layout, app["id"], staff_setup=not args.no_staff_setup))
        return EXIT_OK
    if command == "sync-secrets":
        stored = ops.sync_stored_values(client, layout, guild_id, runner)
        out.line("Stored, without showing any value:")
        for item in stored:
            out.line(f"  {item}")
        _remind(out, False)
        return EXIT_OK
    if command == "staff-roles":
        lines, steps = ops.staff_roles(client, layout, guild_id, args.apply)
        out.line(
            "Mode: apply." if args.apply else "Mode: dry run. Nothing is changed. Add --apply to make these changes."
        )
        for line in lines:
            out.line(f"  {line}")
        if args.apply:
            out.line("")
            out.line("For you, in this order:")
            for number, step in enumerate(steps, 1):
                out.line(f"{number}. {step}")
        return EXIT_OK
    if command == "lockdown":
        if args.hours is None and not args.lift:
            raise SetupError("lockdown needs --hours or --lift")
        out.line(ops.lockdown(client, layout, guild_id, args.hours or 0, args.lift))
        _remind(out, False)
        return EXIT_OK
    if command == "purge-mod-log":
        return _purge(args, layout, client, guild_id, out, stdin, isatty, now)
    return _plan_or_apply(
        args, layout, client, guild_id, out, stdin, isatty, env.get("DISCORD_INTERACTIONS_URL") or None
    )


def _remind(out: Out, to_stderr: bool) -> None:
    """The last words of every session that used the token."""
    write = out.error if to_stderr else out.line
    write("")
    for line in RESET_TOKEN:
        write(line)


def _bot_role(layout: Layout, env, sleep, clock) -> dict | None:
    token = env.get("DISCORD_BOT_TOKEN", "")
    if not token:
        raise SetupError("session-check needs DISCORD_BOT_TOKEN, because it asks Discord about the bot's role")
    client = Client(
        resolve_base(env.get("DISCORD_API_BASE")), token, user_agent(layout), read_only=True, sleep=sleep, clock=clock
    )
    me = client.request("GET", "/users/@me")
    guild = find_guild(client, layout.name, env.get("DISCORD_GUILD_ID") or None)
    roles = client.request("GET", f"/guilds/{guild['id']}/roles")
    return next((r for r in roles if (r.get("tags") or {}).get("bot_id") == me["id"]), None)


def _session_check(layout: Layout, env, out: Out, sleep, clock) -> int:
    state, held, total = ops.role_state(layout, _bot_role(layout, env, sleep, clock))
    if state == "lowered":
        out.line(f"The bot's role is lowered: it holds {held} of the {total} permissions the layout needs.")
        out.line("Now reset the bot token. Open https://discord.com/developers/applications, choose the application,")
        out.line("open Bot and press Reset Token. This tool cannot see whether that is done.")
        return EXIT_OK
    out.line(f"The bot's role is still {state}: it holds {held} of the {total} permissions the layout needs.")
    out.line('Lower it by hand before you finish. Run "python3 -m serverkit stand-down" for the steps.')
    return EXIT_BLOCKED


def _stand_down(args, layout: Layout, env, out: Out, sleep, clock) -> int:
    role = None
    token = env.get("DISCORD_BOT_TOKEN", "")
    if token:
        # only the bot and the role list are read, so this also works while the role is lowered
        client = Client(
            resolve_base(env.get("DISCORD_API_BASE")),
            token,
            user_agent(layout),
            read_only=True,
            sleep=sleep,
            clock=clock,
        )
        me = client.request("GET", "/users/@me")
        guild = find_guild(client, layout.name, env.get("DISCORD_GUILD_ID") or None)
        roles = client.request("GET", f"/guilds/{guild['id']}/roles")
        role = next((r for r in roles if (r.get("tags") or {}).get("bot_id") == me["id"]), None)
    for line in ops.stand_down(layout, role, args.raise_role):
        out.line(line)
    return EXIT_OK


def _rules_text(layout: Layout, out: Out) -> int:
    """The first rules message as plain text, for pasting into Rules Screening, which takes no links by id."""
    channel = layout.channel(layout.server.get("rules_channel", ""))
    if channel is None or not channel.messages:
        raise SetupError("the rules channel holds no managed message")

    def plain(kind: str, name: str) -> str:
        return f"#{name}" if kind == "channel" else f"/{name}" if kind == "command" else name

    contact = contact_email(layout.commands_content) or ""
    title, description = textfmt.split_embed(channel.messages[0])
    out.line(textfmt.render(title, plain, contact))
    out.line()
    out.line(textfmt.plain_markdown(textfmt.render(description, plain, contact)))
    return EXIT_OK


def _check(layout: Layout, out: Out) -> int:
    problems = link_problems(layout)
    if layout.commands.get("content") and layout.commands_content is None:
        problems.append("the command content file is missing")
    if layout.commands_content is not None:
        _, errors = commandset.registration(layout.commands_content, bool(layout.status.get("enabled", False)))
        problems.extend(errors)
    if problems:
        raise SetupError("the layout is not valid:\n  " + "\n  ".join(problems))
    out.line(
        f"{layout.name} layout {layout.hash8} is valid: {len(layout.roles)} roles, "
        f"{len(layout.active_categories)} categories, {len(layout.active_channels)} channels, "
        f"{len(layout.automod)} auto moderation rules and {len(layout.webhooks)} webhooks."
    )
    return EXIT_OK


def _options(args, env_url: str | None) -> Options:
    only = None
    if args.only:
        only = {s.strip() for s in args.only.split(",") if s.strip()}
        unknown = only - set(STEPS)
        if unknown:
            raise SetupError(f"--only names unknown steps: {', '.join(sorted(unknown))}. Steps: {', '.join(STEPS)}")
    prune = None
    if args.prune:
        if len(args.prune) > 1:
            raise SetupError("--prune takes one kind in each run")
        prune = args.prune[0]
        if prune not in PRUNE_KINDS:
            raise SetupError(f"--prune kinds: {', '.join(PRUNE_KINDS)}")
    return Options(
        allow_renames=args.allow_renames,
        prune=prune,
        rotate=list(args.rotate_webhook),
        only=only,
        summary=not args.no_summary,
        interactions_url=env_url,
    )


def _plan_or_apply(args, layout: Layout, client: Client, guild_id: str | None, out: Out, stdin, isatty, url) -> int:
    mode = "apply" if args.command == "apply" else "plan"
    opts = _options(args, url)
    try:
        snap = load_snapshot(client, layout.name, guild_id)
    except ApiError as err:
        if err.status != 403:
            raise
        raise SetupError(
            'the bot is not allowed to read the server. If its role was lowered with "serverkit stand-down", run '
            '"serverkit stand-down --raise" for the permissions to switch back on'
        ) from None
    ctx = Ctx(layout, snap, client, opts)
    members = snap.member_count if snap.member_count is not None else "unknown"
    header = f'{layout.name} layout {layout.hash8} against the server "{snap.guild["name"]}" ({members} members)'
    lines, errors = preflight(ctx)
    if errors:
        plan = Plan(lines, [])
        out.line(header)
        out.line()
        out.line("Preflight")
        for c in lines:
            out.line(out.word(c.word, c.text))
        for message in errors:
            out.line(out.word("error", message))
        return EXIT_SETUP
    plan = build_plan(ctx, opts.only)
    plan.preflight = lines
    if mode == "plan":
        code = decide_exit(plan, mode, None)
        print_plan(out, plan, header, mode, args.format, code)
        return code
    destructive = [c for c in plan.changes if c.destructive and not c.held]
    if destructive and not confirm(out, destructive, layout.name, stdin, isatty):
        return EXIT_SETUP
    print_plan(out, plan, header, mode, args.format, EXIT_OK)
    result = execute(ctx, plan)
    out.line()
    out.line(f"Applied {len(result.applied)} changes.")
    for change, reason in result.blocked:
        out.line(out.word("blocked", f"{change.text}: {reason}"))
    if result.failures:
        for change, message in result.failures:
            out.line(out.word("error", f"{change.text}: {message}"))
        for change, why in result.skipped:
            out.line(out.word("skipped", f"{change.text}: {why}"))
        out.line("Not applied:")
        for c in result.not_applied:
            out.line(out.word("waiting", c.text))
        out.line("Run it again to resume. Every step compares before it writes.")
    elif opts.summary and result.applied:
        try:
            post_summary(ctx, result.applied)
        except ApiError as exc:
            out.line(out.word("warning", f"the summary could not be posted: {exc}"))
    code = decide_exit(plan, mode, result)
    _remind(out, args.format == "json")
    return code


def _purge(args, layout: Layout, client: Client, guild_id: str | None, out: Out, stdin, isatty, now) -> int:
    age = ops.parse_age(args.older_than)
    ctx = ops.make_snapshot_ctx(client, layout, guild_id)
    names = [
        layout.server.get("public_updates_channel", "moderator-only"),
        layout.server.get("summary_channel", "mod-log"),
    ]
    found = ops.purge_candidates(client, ctx, list(dict.fromkeys(names)), age, now())
    if not found:
        out.line("Nothing is older than that.")
        _remind(out, False)
        return EXIT_OK
    where = ", ".join("#" + n for n in dict.fromkeys(f["channel"] for f in found))
    threads = sum(1 for f in found if f["kind"] == "thread")
    out.line(f"{len(found)} items are older than {args.older_than}, in {where}, including {threads} whole threads.")
    change = Change("channels", "delete", f"{len(found)} old messages and threads", None, destructive=True)
    if not confirm(out, [change], layout.name, stdin, isatty):
        return EXIT_SETUP
    done, skipped = ops.purge(client, ctx, found)
    out.line(f"Deleted {done} items.")
    if skipped:
        out.line(f"Skipped {len(skipped)} items that Discord refused. They stay until they can be removed by hand:")
        for line in skipped[:20]:
            out.line(f"  {line}")
    _remind(out, False)
    return EXIT_BLOCKED if skipped else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
