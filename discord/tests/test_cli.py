"""Every command, flag and exit code and the confirmation that guards anything that cannot be undone."""

from __future__ import annotations

import io
import json
import re
from datetime import UTC, datetime, timedelta

import pytest
from conftest import ROOT, words
from fake_discord import TEXT
from helpers import deletes, layout_data, methods, write_layout

from serverkit import cli, ops
from serverkit.layout import load

ANY_PROMPT = "Type the server name"


def built(server):
    assert server.apply().code == 0
    return server


# ---- exit codes ------------------------------------------------------------------------------------


def test_exit_0_when_the_server_matches_and_nothing_waits(server):
    built(server)
    assert server.plan().code == 0
    assert server.apply().code == 0


def test_exit_1_when_a_run_stops_on_an_error_that_retries_do_not_cure(server):
    server.fake.fail_next(r"/auto-moderation/rules$", "500", times=99, method="POST")
    result = server.apply()
    assert result.code == 1
    assert "Not applied:" in result.out and "Run it again to resume" in result.out
    # what was done before the stop is reported and kept
    assert "Applied " in result.out and server.fake.by_name("general")


def test_exit_2_for_each_way_of_not_being_able_to_start(server, tmp_path):
    assert server.run("plan", "--prune", "nothing").code == 2
    assert server.run("plan", "--prune", "channels", "--prune", "roles").code == 2
    assert server.run("plan", "--max-wait").code == 2
    assert server.run("frobnicate").code == 2
    assert server.run("plan", env={"DISCORD_BOT_TOKEN": ""}).code == 2
    assert server.run("plan", layout=tmp_path / "absent.toml").code == 2
    assert server.run("plan", env={"DISCORD_API_BASE": "https://discord.com/api/v10"}).code == 2
    assert server.run("lockdown").code == 2


def test_exit_3_when_something_waits_for_the_owner(make_server):
    h = make_server(community=False)
    assert h.plan().code == 3
    assert h.apply().code == 3


def test_exit_4_is_for_a_plan_with_changes_waiting(server):
    built(server)
    server.fake.guild["verification_level"] = 0
    assert server.plan().code == 4


def test_the_lowest_code_other_than_zero_wins(make_server):
    # Community is off, so something is blocked (3) and there are changes waiting (4): 3 wins
    h = make_server(community=False)
    assert h.plan().code == 3


def test_the_default_command_is_plan_and_changes_nothing(server):
    result = server.run()
    assert result.code == 4 and "Mode: plan" in result.out
    assert methods(server.fake) == set()


def test_version_and_help_exit_0(server):
    assert server.run("--version").code == 0
    assert server.run("--help").code == 0


# ---- finding the right server --------------------------------------------------------------------------


def test_a_server_with_another_name_is_never_touched(make_server):
    h = make_server(name="Somewhere else")
    result = h.apply()
    assert result.code == 2
    assert "not in a server called" in result.err and "Somewhere else" in result.err
    assert methods(h.fake) == set()


def test_two_servers_with_one_name_need_the_guild_id_from_the_environment(make_server, layout):
    h = make_server()
    h.fake.other_guilds.append({"id": "1" + "2" * 10, "name": layout.name})
    result = h.plan()
    assert result.code == 2 and "DISCORD_GUILD_ID" in result.err
    ok = h.plan(env={"DISCORD_GUILD_ID": h.fake.guild_id})
    assert ok.code == 4
    wrong = h.plan(env={"DISCORD_GUILD_ID": "1" + "2" * 10})
    assert wrong.code == 2


def test_no_id_appears_in_any_message_the_script_prints(make_server, layout):
    h = make_server(name="Somewhere else")
    result = h.plan()
    assert not re.search(r"\d{17,20}", result.out + result.err)


# ---- renames and deletion ----------------------------------------------------------------------------------


def old_log_server(make_server, layout):
    h = make_server()
    fake = h.fake
    fake.add_channel("Old", 4)
    fake.add_channel("bot-logs", TEXT, parent="Old")
    return h


def renamed_layout(tmp_path):
    data = layout_data()
    for channel in data["channels"]:
        if channel["name"] == "mod-log":
            channel["previous_names"] = ["bot-logs"]
    return write_layout(tmp_path, data)


def test_a_rename_is_held_back_without_the_flag_and_nothing_is_created_under_the_new_name(
    make_server, layout, tmp_path
):
    h = old_log_server(make_server, layout)
    path = renamed_layout(tmp_path)
    plan = h.plan(layout=path)
    assert plan.code == 3
    assert any("bot-logs" in t and "held back, needs --allow-renames" in t for w, t in words(plan.out) if w == "rename")
    result = h.apply(layout=path)
    assert result.code == 3
    names = [c["name"] for c in h.fake.channels.values()]
    assert "bot-logs" in names and "mod-log" not in names
    assert deletes(h.fake) == []


def test_allow_renames_without_a_terminal_changes_nothing(make_server, layout, tmp_path):
    h = old_log_server(make_server, layout)
    before = h.fake.state()
    result = h.apply("--allow-renames", layout=renamed_layout(tmp_path), tty=False, stdin=layout.name + "\n")
    assert result.code == 2
    assert "needs a terminal" in result.err
    assert h.fake.state() == before


@pytest.mark.parametrize("answer", ["", "wrong", "server", "  ", "yes"])
def test_a_wrong_answer_cancels_and_changes_nothing(make_server, layout, tmp_path, answer):
    h = old_log_server(make_server, layout)
    before = h.fake.state()
    result = h.apply("--allow-renames", layout=renamed_layout(tmp_path), tty=True, stdin=answer + "\n")
    assert result.code == 2 and "Cancelled" in result.out
    assert ANY_PROMPT in result.out
    assert h.fake.state() == before


def test_the_exact_server_name_lets_a_rename_through(make_server, layout, tmp_path):
    h = old_log_server(make_server, layout)
    result = h.apply("--allow-renames", layout=renamed_layout(tmp_path), tty=True, stdin=layout.name + "\n")
    assert result.code == 0, result.out + result.err
    names = [c["name"] for c in h.fake.channels.values()]
    assert "mod-log" in names and "bot-logs" not in names
    # it is the same channel, so what was said in it is kept
    assert h.plan(layout=renamed_layout(tmp_path)).code == 0


def test_a_plain_apply_does_not_prompt_even_without_a_terminal(server):
    assert server.apply(tty=False, stdin="").code == 0


UNMANAGED = {
    "channels": lambda f: f.add_channel("someone-made-this", TEXT),
    "roles": lambda f: f.add_role("Someone made this", 0, position=2),
    "automod": lambda f: f.automod.update(
        {
            "77": {
                "id": "77",
                "name": "Mine",
                "event_type": 1,
                "trigger_type": 1,
                "trigger_metadata": {"keyword_filter": ["x"]},
                "actions": [{"type": 1, "metadata": {}}],
                "enabled": True,
                "exempt_roles": [],
                "exempt_channels": [],
            }
        }
    ),
    "webhooks": lambda f: f.webhooks.update(
        {
            "88": {
                "id": "88",
                "type": 1,
                "channel_id": f.by_name("general")["id"],
                "name": "Hand made",
                "application_id": None,
                "guild_id": f.guild_id,
                "token": "t",
                "url": "http://127.0.0.1/h",
            }
        }
    ),
    "messages": lambda f: f.add_message("rules", "an extra line from the bot"),
    "commands": lambda f: f.commands.append({"id": "55", "name": "extra", "description": "x", "type": 1}),
    "overwrites": lambda f: f.by_name("general")["permission_overwrites"].append(
        {"id": f.add_role("Someone", 0, position=2)["id"], "type": 0, "allow": "1024", "deny": "0"}
    ),
}


@pytest.mark.parametrize("kind", list(UNMANAGED))
def test_prune_deletes_one_kind_only_after_the_typed_name(server, layout, kind):
    built(server)
    fake = server.fake
    UNMANAGED[kind](fake)
    before_other = {
        k: len(v)
        for k, v in (
            ("channels", fake.channels),
            ("roles", fake.roles),
            ("automod", fake.automod),
            ("webhooks", fake.webhooks),
        )
    }
    # without a terminal or with the wrong words, nothing happens
    state = fake.state()
    assert server.apply("--prune", kind, tty=False).code == 2
    assert server.apply("--prune", kind, tty=True, stdin="no\n").code == 2
    assert fake.state() == state
    plan = server.plan("--prune", kind)
    assert any(w == "delete" for w, _ in words(plan.out)), plan.out
    result = server.apply("--prune", kind, tty=True, stdin=layout.name + "\n")
    assert result.code == 0, result.out + result.err
    assert "DELETE" in methods(fake) or kind in ("overwrites", "commands")
    after = server.plan()
    if kind == "overwrites":
        assert not [t for w, t in words(after.out) if w == "unmanaged" and "overwrite" in t]
    if kind == "channels":
        assert not [c for c in fake.channels.values() if c["name"] == "someone-made-this"]
        assert len(fake.roles) == before_other["roles"]
    if kind == "roles":
        assert not [r for r in fake.roles.values() if r["name"] == "Someone made this"]
        assert len(fake.channels) == before_other["channels"]
    if kind == "webhooks":
        assert "88" not in fake.webhooks
    if kind == "automod":
        assert "77" not in fake.automod
    if kind == "commands":
        assert "extra" not in {c["name"] for c in fake.commands}


def test_unmanaged_commands_survive_a_plain_apply_and_the_bulk_overwrite(server):
    built(server)
    fake = server.fake
    fake.commands.append({"id": "55", "name": "extra", "description": "x", "type": 1})
    fake.commands = [c for c in fake.commands if c["name"] != "help"]
    assert server.apply().code == 0
    names = {c["name"] for c in fake.commands}
    assert "extra" in names and "help" in names


def test_the_prompt_says_deleting_cannot_be_undone(server, layout):
    built(server)
    server.fake.add_channel("someone-made-this", TEXT)
    out = server.apply("--prune", "channels", tty=True, stdin="no\n").out
    assert "cannot be undone" in out
    assert "someone-made-this" in out


def test_rotate_webhook_replaces_one_webhook_after_the_typed_name(server, layout):
    built(server)
    fake = server.fake
    name = layout.webhooks[0]["name"]
    old = next(h for h in fake.webhooks.values() if h["name"] == name)
    assert server.apply("--rotate-webhook", name, tty=False).code == 2
    assert old["id"] in fake.webhooks
    result = server.apply("--rotate-webhook", name, tty=True, stdin=layout.name + "\n")
    assert result.code == 0, result.out + result.err
    new = next(h for h in fake.webhooks.values() if h["name"] == name)
    assert new["id"] != old["id"] and new["token"] != old["token"]
    assert len(fake.webhooks) == len(
        [h for h in layout.webhooks if layout.channel_active(layout.channel(h["channel"]))]
    )
    assert server.run("plan", "--rotate-webhook", "No such hook").code == 2


# ---- invite, lockdown, purge, secrets, content ------------------------------------------------------------------


def test_invite_url_carries_the_scopes_and_exactly_the_permissions_the_layout_needs(server, layout):
    result = server.run("invite-url")
    assert result.code == 0
    url = result.out.strip()
    assert url.startswith("https://discord.com/oauth2/authorize?")
    assert f"permissions={layout.bot_permissions(staff_setup=True)}" in url
    assert "scope=bot%20applications.commands" in url
    assert f"client_id={server.fake.app_id}" in url
    assert server.fake.token not in result.out
    assert not layout.bot_permissions(staff_setup=True) & 8
    assert methods(server.fake) == set()


def test_lockdown_pauses_and_lifts(server):
    assert server.run("lockdown", "--hours", "6").code == 0
    data = server.fake.guild["incidents_data"]
    assert data["invites_disabled_until"] and data["dms_disabled_until"]
    until = datetime.fromisoformat(data["invites_disabled_until"])
    assert timedelta(hours=5) < until - datetime.now(UTC) <= timedelta(hours=6, minutes=1)
    assert server.run("lockdown", "--lift").code == 0
    assert server.fake.guild["incidents_data"] == {"invites_disabled_until": None, "dms_disabled_until": None}
    assert server.fake.audit[-1]["reason"].endswith("lift the lockdown")


@pytest.mark.parametrize("hours", ["0", "-1", "25", "100"])
def test_lockdown_refuses_hours_outside_the_limit(server, hours):
    assert server.run("lockdown", "--hours", hours).code == 2
    assert methods(server.fake) == set()


def seed_logs(fake, layout):
    old = timedelta(days=400)
    for channel in (layout.server["public_updates_channel"], layout.server["summary_channel"]):
        fake.add_message(channel, "old entry", age=old)
        fake.add_message(channel, "recent entry", age=timedelta(days=3))
    return fake


def test_purge_deletes_only_old_entries_after_the_typed_name(server, layout):
    built(server)
    fake = seed_logs(server.fake, layout)
    total = sum(len(v) for v in fake.messages.values())
    assert server.run("purge-mod-log", "--older-than", "365d", tty=False).code == 2
    assert server.run("purge-mod-log", "--older-than", "365d", tty=True, stdin="no\n").code == 2
    assert sum(len(v) for v in fake.messages.values()) == total
    result = server.run("purge-mod-log", "--older-than", "365d", tty=True, stdin=layout.name + "\n")
    assert result.code == 0 and "Deleted 2 items" in result.out
    contents = [m["content"] for v in fake.messages.values() for m in v]
    assert "old entry" not in contents and contents.count("recent entry") == 2


def test_purge_with_nothing_old_or_a_bad_age(server, layout):
    built(server)
    assert server.run("purge-mod-log", "--older-than", "365d").out.startswith("Nothing is older than that.")
    assert server.run("purge-mod-log", "--older-than", "a year").code == 2
    assert server.run("purge-mod-log", "--older-than", "0d").code == 2


def test_sync_secrets_stores_each_address_on_standard_input_and_prints_none(server, layout):
    built(server)
    result = server.run("sync-secrets")
    assert result.code == 0, result.out + result.err
    active = [h for h in layout.webhooks if layout.channel_active(layout.channel(h["channel"]))]
    # the webhooks, the public key, the staff role ids and the ticket tag ids when there is a ticket forum
    tag_job = 1 if (layout.commands_content or {}).get("ticket_kinds") else 0
    # and one forum tag id for each relay route that posts into a forum
    forum_routes = [r for r in layout.relay.get("discussions", {}).values() if r.get("tag_secret")]
    assert len(result.stored) == len(active) + 2 + tag_job + len(forum_routes)
    fake = server.fake
    for command, value in result.stored:
        # the value is never on the command line, where a process list would show it
        assert value not in command and all(value not in part for part in command)
        assert fake.token not in value
    github = [c for c, _ in result.stored if c[0] == "gh"]
    assert all(c[:3] == ["gh", "secret", "set"] and "--env" in c and "community" in c for c in github)
    assert any(layout.webhooks[0]["secret"] in c for c in github)
    key = next(v for c, v in result.stored if "DISCORD_PUBLIC_KEY" in c)
    assert key == fake.verify_key
    hook_values = [
        v
        for c, v in result.stored
        if v != fake.verify_key
        and "STAFF_ROLE_IDS" not in c
        and "TICKET_TAG_IDS" not in c
        and not any(name.startswith("DISCORD_TAG_") for name in c)
    ]
    assert all(any(v == h["url"] for h in fake.webhooks.values()) for v in hook_values)
    for value in [*hook_values, key]:
        assert value not in result.out + result.err


def test_sync_secrets_before_apply_says_what_is_missing(server):
    result = server.run("sync-secrets")
    assert result.code == 2 and "does not exist yet" in result.err
    assert result.stored == []


def test_sync_secrets_reports_a_failing_tool_without_the_value(server, layout):
    built(server)
    out, err = io.StringIO(), io.StringIO()

    def failing(command, value):
        raise OSError("tool not found")

    code = cli.main(
        ["sync-secrets", "--layout", str(layout.path)],
        env={"DISCORD_BOT_TOKEN": server.fake.token, "DISCORD_API_BASE": server.fake.url},
        stdout=out,
        stderr=err,
        runner=failing,
        cwd=ROOT,
    )
    assert code == 2 and "could not run" in err.getvalue()
    assert "tok" not in err.getvalue()


def test_export_content_writes_and_checks_the_workers_json(server, tmp_path):
    path = write_layout(tmp_path, layout_data())
    assert server.run("export-content", "--check", layout=path).code == 1
    assert server.run("export-content", layout=path).code == 0
    target = tmp_path / "worker" / "src" / "content.generated.json"
    assert target.is_file()
    assert server.run("export-content", "--check", layout=path).code == 0
    target.write_text(target.read_text() + " ")
    assert server.run("export-content", "--check", layout=path).code == 1
    data = json.loads(target.read_text())
    assert data["commands"] and data["schema"] == 1


def test_the_committed_worker_json_is_current():
    layout = load(sorted((ROOT / "layout").glob("*.toml"))[0])
    target = ROOT / "worker" / "src" / "content.generated.json"
    if not target.is_file():
        pytest.skip("the worker has not generated its content yet")
    ok, _ = ops.export_content(layout, check=True)
    assert ok, "run: python -m serverkit export-content"


def test_the_interactions_address_is_set_when_given_and_only_then(server):
    built(server)
    assert server.fake.app["interactions_endpoint_url"] is None
    url = "http://127.0.0.1:8787/interactions"
    plan = server.plan(env={"DISCORD_INTERACTIONS_URL": url})
    assert plan.code == 4 and any("interactions address" in t for _w, t in words(plan.out))
    assert server.apply(env={"DISCORD_INTERACTIONS_URL": url}).code == 0
    assert server.fake.app["interactions_endpoint_url"] == url
    count = server.fake.write_count
    assert server.apply(env={"DISCORD_INTERACTIONS_URL": url}).code == 0
    assert server.fake.write_count == count


def test_the_status_command_is_registered_only_when_the_layout_switches_it_on(server, tmp_path):
    data = layout_data()
    if "status" not in data or not any(c["name"] == "status" for c in load(server.path).commands_content["commands"]):
        pytest.skip("this project has no status command")
    data["status"]["enabled"] = True
    path = write_layout(tmp_path, data)
    assert server.apply(layout=path).code == 0
    assert "status" in {c["name"] for c in server.fake.commands}


def test_a_message_posted_by_the_script_never_pings(server, layout):
    built(server)
    sent = [m for v in server.fake.messages.values() for m in v]
    assert sent
    # every message of the script switches off previews and none holds a mention that would ping everyone
    assert not any("@everyone" in m["content"] or "@here" in m["content"] for m in sent)
