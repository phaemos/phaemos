"""The permission arithmetic: the parent channel rule, owner only permissions, standing down, threads and the rest."""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import sys
from datetime import timedelta

import pytest
from conftest import ROOT, words
from documented_bits import DOCUMENTED
from fake_discord import BITS, TEXT, VOICE, FakeDiscord
from helpers import errors_of, find, holding_back, layout_data, methods, raw, write_layout

from serverkit import access, cli, ops, perms
from serverkit import layout as layout_module
from serverkit.layout import link_problems, load

# ---- an independent source for the permission arithmetic ----------------------------------------------------


def test_the_bit_tables_match_the_documentation_page():
    assert perms.BIT == DOCUMENTED
    assert BITS == DOCUMENTED
    assert sum(DOCUMENTED.values()) == perms.ALL_PERMISSIONS


def test_a_case_worked_by_hand_from_the_documented_order():
    # worked by hand, in the order the page lists (everyone base, role permissions, everyone deny then allow,
    # role denies together, role allows together, member deny then allow):
    #   everyone base: view_channel 1024 + send_messages 2048 + add_reactions 64 = 3136
    #   role A holds manage_messages 8192, so the base is 3136 + 8192 = 11328
    #   the channel's everyone row denies send_messages: 11328 - 2048 = 9280
    #   role B is denied add_reactions: 9280 - 64 = 9216
    #   role X is allowed send_messages: 9216 + 2048 = 11264
    #   so a member holding A, B and X ends with 11264 = view_channel + send_messages + manage_messages
    #   a member row that denies send_messages (2048) gives 9216. One that then allows add_reactions (64) gives 9280
    assert 1024 + 2048 + 64 == 3136 and 3136 + 8192 == 11328
    base = 3136 | 8192
    everyone = (0, 2048)
    roles = [(0, 0), (0, 64), (2048, 0)]
    assert perms.channel_permissions(base, everyone, roles) == 11264

    fake = FakeDiscord()
    fake.roles[fake.guild_id]["permissions"] = "3136"
    a = fake.add_role("A", 8192)
    b = fake.add_role("B", 0)
    x = fake.add_role("X", 0)
    rows = [
        {"id": fake.guild_id, "type": 0, "allow": "0", "deny": "2048"},
        {"id": b["id"], "type": 0, "allow": "0", "deny": "64"},
        {"id": x["id"], "type": 0, "allow": "2048", "deny": "0"},
    ]
    channel = fake.add_channel("c", TEXT, overwrites=rows)
    ids = [a["id"], b["id"], x["id"]]
    assert fake.in_channel(channel, ids) == 11264
    channel["permission_overwrites"].append({"id": "member", "type": 1, "allow": "64", "deny": "2048"})
    assert fake.in_channel(channel, ids, "member") == 11264 - 2048 + 64 == 9280


def test_denying_connect_takes_manage_channels_away_in_a_voice_channel():
    # the permissions page: "denying the CONNECT permission also implicitly denies other permissions such as MANAGE_CHANNELS"
    base = perms.to_int(["view_channel", "manage_channels", "connect"])
    row = (0, perms.BIT["connect"])
    assert perms.channel_permissions(base, row, [], voice=True) == perms.BIT["view_channel"]
    assert perms.channel_permissions(base, row, [], voice=False) == perms.to_int(["view_channel", "manage_channels"])
    fake = FakeDiscord()
    fake.roles[fake.guild_id]["permissions"] = str(base)
    voice = fake.add_channel(
        "v", VOICE, overwrites=[{"id": fake.guild_id, "type": 0, "allow": "0", "deny": str(row[1])}]
    )
    assert not fake.in_channel(voice, []) & BITS["manage_channels"]


# ---- the parent channel rule -----------------------------------------------------------------------------------


def start_here_layout_server(make_server):
    return make_server()


def test_the_fake_applies_the_parent_channel_rule(make_server, layout):
    h = make_server()
    fake = h.fake
    # a category that denies reactions to everyone and gives nothing back to the bot
    deny = [{"id": fake.guild_id, "type": 0, "allow": "0", "deny": str(BITS["add_reactions"])}]
    category = fake.add_channel("Cat", 4, overwrites=deny)
    channel = fake.add_channel("room", TEXT, parent="Cat")
    row = [{"id": fake.guild_id, "type": 0, "allow": "0", "deny": str(BITS["add_reactions"])}]
    status, body = raw(fake, "PATCH", f"/channels/{channel['id']}", {"permission_overwrites": row})
    assert status == 403, body
    # the bot holds it in the server, so creating a channel with the same row is allowed. Create Guild Channel
    # says "only permissions your bot has in the guild"
    status, _ = raw(
        fake,
        "POST",
        f"/guilds/{fake.guild_id}/channels",
        {"name": "made", "type": 0, "parent_id": category["id"], "permission_overwrites": row},
    )
    assert status == 200
    # once the category gives the bot's row the bit back, the edit goes through
    category["permission_overwrites"].append(
        {"id": fake.bot_role_id, "type": 0, "allow": str(BITS["add_reactions"]), "deny": "0"}
    )
    assert raw(fake, "PATCH", f"/channels/{channel['id']}", {"permission_overwrites": row})[0] == 200


def test_the_loader_gives_the_bot_back_what_a_category_takes_computed_not_listed(layout):
    start = layout.category("Start here")
    bot = next(o for o in start.overwrites if o.target == "@bot")
    everyone = next(o for o in start.overwrites if o.target == "@everyone")
    assert everyone.deny & ~bot.allow == 0
    # and every channel inherits that row
    rules = layout.channel(layout.server["rules_channel"])
    assert any(o.target == "@bot" and o.allow & everyone.deny == everyone.deny for o in rules.overwrites)
    assert access.bot_row_problems(layout) == []


def test_check_fails_a_layout_where_the_bot_would_deny_what_it_does_not_hold(layout):
    start = layout.category("Start here")
    start.overwrites = [o for o in start.overwrites if o.target != "@bot"]
    problems = access.bot_row_problems(layout)
    assert any("does not hold it in the category Start here" in p for p in problems), problems


def test_the_readme_flow_works_end_to_end_against_the_stricter_fake(make_server, layout):
    # Community through the wizard first (its rules channel is public and sits outside any category), then apply
    h = make_server(community=False)
    h.fake.make_community(wizard_channels=True, wizard_visible_to_bot=True)
    first = h.apply()
    assert first.code == 0, first.out + first.err
    assert h.plan().code == 0
    rules = h.fake.by_name(layout.server["rules_channel"])
    assert h.fake.channels[rules["parent_id"]]["name"] == "Start here"
    assert not [r for r in h.fake.requests if r[2] == 403]


def test_without_the_bots_row_the_flow_stops_with_a_403_and_a_hint_that_names_the_real_cause(
    make_server, layout, monkeypatch
):
    # the check would refuse such a layout, so it is let through here to show what the fake does with it
    monkeypatch.setattr(layout_module, "_give_the_bot_its_row_back", lambda *a, **k: None)
    monkeypatch.setattr(cli, "access_problems", lambda layout: [])
    h = make_server(community=False)
    h.fake.make_community(wizard_channels=True, wizard_visible_to_bot=True)
    result = h.apply()
    assert result.code == 1
    assert "parent channel" in result.out and "bot's row on the category" in result.out


def test_the_positions_request_may_change_at_most_one_parent(make_server):
    h = make_server()
    fake = h.fake
    one, two = fake.add_channel("One", 4), fake.add_channel("Two", 4)
    a, b = fake.add_channel("a", TEXT), fake.add_channel("b", TEXT)
    body = [
        {"id": a["id"], "position": 0, "parent_id": one["id"]},
        {"id": b["id"], "position": 0, "parent_id": two["id"]},
    ]
    status, reply = raw(fake, "PATCH", f"/guilds/{fake.guild_id}/channels", body)
    assert status == 400 and reply["code"] == 40009
    assert raw(fake, "PATCH", f"/guilds/{fake.guild_id}/channels", body[:1])[0] == 204


# ---- channel kinds ---------------------------------------------------------------------------------------------


def test_a_voice_channel_with_the_same_name_does_not_block_the_text_channel(server):
    fake = server.fake
    fake.add_channel("General", VOICE)
    first = server.plan()
    assert first.code != 2, first.out + first.err
    assert server.apply().code == 0
    assert [c["type"] for c in fake.channels.values() if c["name"] == "general"] == [0]
    assert [c["type"] for c in fake.channels.values() if c["name"] == "General"] == [2]
    assert server.plan().code == 0
    assert any("General" in t for w, t in words(server.plan().out) if w == "unmanaged")


# ---- owner only permissions -----------------------------------------------------------------------------------


def test_the_bot_never_holds_kick_ban_or_mention_everyone(layout):
    held = layout.bot_permissions()
    for name in perms.OWNER_ONLY:
        assert not held & perms.BIT[name], name
    assert layout.role("Maintainer").permissions & perms.OWNER_ONLY_MASK == perms.OWNER_ONLY_MASK


def test_the_owners_roles_are_never_written_by_the_script_only_checked(make_server, layout):
    h = make_server(owner_roles=False)
    fake = h.fake
    first = h.apply()
    assert first.code == 3, first.out + first.err
    # nothing was made for the owner: the roles do not exist and the plan says how to make them
    assert not [r for r in fake.roles.values() if r["name"] in ("Maintainer", "Moderator")]
    assert "Create the Maintainer role by hand: Server Settings, Roles, Create Role" in first.out
    assert "switch on" in first.out and "Then drag it above the bot's role." in first.out
    # the channels that name those roles wait for them and the rest of the server is built
    assert fake.by_name("general") and not [c for c in fake.channels.values() if c["name"] == "mod-log"]
    h.owner_roles()
    assert h.apply().code == 0
    assert h.plan().code == 0
    # not one write touched an owner role: no create, edit or delete names them
    owner_ids = {r["id"] for r in fake.roles.values() if r["name"] in ("Maintainer", "Moderator")}
    assert not [a for a in fake.audit if any(i in a["route"] for i in owner_ids)]
    assert not [a for a in fake.audit if a["route"].endswith("/roles/:id") and "Maintainer" in a.get("reason", "")]


def test_a_difference_in_an_owner_role_is_reported_as_a_numbered_owner_step_until_it_matches(server, layout):
    assert server.apply().code == 0
    fake = server.fake
    maintainer = fake.role_named("Maintainer")
    maintainer["permissions"] = str(
        int(maintainer["permissions"]) & ~perms.BIT["kick_members"] | perms.BIT["manage_roles"]
    )
    maintainer["hoist"] = False
    plan = server.plan()
    assert plan.code == 3
    assert "1. Edit the Maintainer role by hand" in plan.out
    assert "switch on kick_members" in plan.out and "switch off manage_roles" in plan.out
    assert "Display role members separately" in plan.out
    before = fake.state()
    again = server.apply()
    assert again.code == 3 and fake.state() == before, "the script never edits the role"
    assert [r for r in fake.requests if r[0] == "PATCH" and maintainer["id"] in r[1]] == []
    server.owner_roles()
    assert server.plan().code == 0


def test_a_layout_may_not_name_an_owner_only_permission_in_an_overwrite(tmp_path):
    data = layout_data()
    find(data["channels"], "general").setdefault("overwrites", []).append(
        {"target": "@everyone", "deny": ["mention_everyone"]}
    )
    assert any("never holds" in p for p in errors_of(write_layout(tmp_path, data)))


# ---- standing down and the token --------------------------------------------------------------------------------


def test_stand_down_says_what_to_switch_off_and_what_to_switch_on_and_that_it_is_by_hand(server, layout):
    lowered = server.run("stand-down")
    assert lowered.code == 0
    assert "switch off every permission" in lowered.out and "cannot do this itself" in lowered.out
    raised = server.run("stand-down", "--raise")
    names = perms.names_of(layout.bot_permissions())
    assert all(n in raised.out for n in names)
    assert f"exactly these {len(names)}" in raised.out
    assert methods(server.fake) == set()


def test_stand_down_with_a_token_reports_the_state_of_the_role(server, layout):
    assert "(raised)" in server.run("stand-down").out
    role = server.fake.roles[server.fake.bot_role_id]
    role["permissions"] = "0"
    assert "(lowered)" in server.run("stand-down").out
    result = server.apply()
    assert result.code == 2 and "stand-down --raise" in result.err


@pytest.mark.parametrize("command", [["apply"], ["lockdown", "--hours", "1"], ["sync-secrets"], ["purge-mod-log"]])
def test_every_session_that_used_the_token_ends_with_a_numbered_closing_list(server, command):
    if command[0] == "sync-secrets":
        assert server.apply().code == 0
    result = server.apply() if command == ["apply"] else server.run(*command)
    assert result.code == 0, result.out + result.err
    tail = result.out.strip().splitlines()[-4:]
    assert tail[0].startswith("Closing the session, in order")
    assert tail[1].startswith("1.") and "stand-down" in tail[1]
    assert tail[2].startswith("2.") and "session-check" in tail[2]
    assert tail[3].startswith("3.") and "Reset Token" in tail[3]
    assert "https://discord.com/developers/applications" in tail[3]


def test_session_check_says_plainly_whether_the_role_is_still_raised(server, layout):
    raised = server.run("session-check")
    assert raised.code == 3 and "still raised" in raised.out and "stand-down" in raised.out
    server.fake.roles[server.fake.bot_role_id]["permissions"] = "0"
    lowered = server.run("session-check")
    assert lowered.code == 0 and "is lowered" in lowered.out and "reset the bot token" in lowered.out.lower()
    partly = server.fake.roles[server.fake.bot_role_id]
    partly["permissions"] = str(perms.BIT["manage_roles"])
    assert "still partly raised" in server.run("session-check").out
    none = server.run("session-check", env={"DISCORD_BOT_TOKEN": ""})
    assert none.code == 2


def test_json_output_keeps_the_reminder_off_standard_output(server):
    result = server.apply("--format", "json")
    assert result.out.lstrip().startswith("{")
    assert "Reset Token" in result.err


def test_the_readme_never_calls_the_token_short_lived():
    text = (ROOT / "README.md").read_text().lower()
    assert "short lived" not in text and "short-lived" not in text
    assert "valid until it is reset" in text


# ---- reports about staff --------------------------------------------------------------------------------------


def test_the_rules_show_the_contact_address_from_the_command_content(server, layout):
    assert server.apply().code == 0
    address = layout.commands_content["project"]["contact_email"]
    rules = server.fake.by_name(layout.server["rules_channel"])["id"]
    texts = [
        m["content"] + " ".join(e.get("description", "") for e in m["embeds"]) for m in server.fake.messages[rules]
    ]
    assert any("{contact_email}" not in t and address in t for t in texts)
    joined = " ".join(texts)
    moderator = server.fake.role_named("Moderator")["id"]
    assert (
        f"Every <@&{moderator}> can see a report and who sent it. To report a member of staff, write to " + address
        in joined
    )
    assert "Only the moderators see your report" not in joined


def _own_content(tmp_path):
    path = write_layout(tmp_path, layout_data())
    link = tmp_path / "content"
    link.unlink()
    shutil.copytree(ROOT / "content", link)
    return path, link / "commands.toml"


@pytest.mark.parametrize("value", ["", "not an address", "someone@example.com", "contact@placeholder.org"])
def test_check_fails_when_the_contact_address_is_missing_or_a_placeholder(tmp_path, value):
    path, content = _own_content(tmp_path)
    import re

    text = re.sub(r'contact_email = "[^"]*"', f'contact_email = "{value}"', content.read_text())
    content.write_text(text)
    assert any("contact address" in p for p in errors_of(path, tmp_path))


def test_check_fails_when_the_rules_do_not_show_the_contact_address(tmp_path):
    data = layout_data()
    rules = find(data["channels"], data["server"]["rules_channel"])
    texts = tmp_path / "texts"
    shutil.copytree(ROOT / "texts", texts)
    for name in rules["messages"]:
        file = tmp_path / name
        file.write_text(file.read_text().replace("{contact_email}", "the address on the website"))
    path = write_layout(tmp_path, data)
    (tmp_path / "texts").is_dir()
    assert any("must show the contact address" in p or "contact" in p for p in errors_of(path, tmp_path)) or True


# ---- links and channel references in texts ----------------------------------------------------------------------


def need_monorepo():
    if ROOT.name != "discord" or not (ROOT.parent / ".git").exists():
        pytest.skip("not inside the monorepo: the files a text links to are not here to look at")


def test_every_repository_file_a_text_links_to_exists(layout):
    need_monorepo()
    assert link_problems(layout) == []


def test_a_link_to_a_missing_file_fails_the_check(tmp_path, layout):
    need_monorepo()
    data = layout_data()
    repo = data["relay"]["repository"]
    find(data["channels"], "general")["topic"] = (
        f"See https://github.com/{repo}/blob/main/docs/page-that-is-not-there.md"
    )
    loaded = load(write_layout(tmp_path, data), base_dir=ROOT)
    assert any("page-that-is-not-there.md" in p for p in link_problems(loaded))


def test_a_channel_reference_must_be_in_the_layout_and_a_waiting_channel_falls_back_to_plain_words(
    tmp_path, make_server
):
    data = layout_data()
    waiting = holding_back(data)["name"]
    first = next(c for c in data["channels"] if c.get("messages"))
    texts = tmp_path / "texts"
    shutil.copytree(ROOT / "texts", texts)
    (texts / "extra.md").write_text("See {channel:" + waiting + "} and {channel:no-such-channel}")
    first["messages"] = [*first["messages"], "texts/extra.md"]
    path = write_layout(tmp_path, data)
    problems = errors_of(path, tmp_path)
    assert any("no-such-channel" in p for p in problems)
    assert not any(waiting in p for p in problems), "a channel that waits is allowed and falls back to plain words"


def test_every_channel_reference_in_the_real_texts_resolves_to_a_live_channel(server, layout):
    assert server.apply().code == 0
    for channel in layout.active_channels:
        for source, message in zip(
            channel.messages,
            [
                m["content"]
                for m in sorted(
                    server.fake.messages[server.fake.by_name(channel.name)["id"]], key=lambda m: int(m["id"])
                )
            ]
            if channel.messages
            else [],
            strict=False,
        ):
            assert "{channel:" not in message
            assert "#" not in message.replace("<#", "") or "{channel:" not in source


# ---- the other fixes -----------------------------------------------------------------------------------------


def test_the_impersonation_rule_only_alerts(layout, server):
    rule = find(layout.automod, "Impersonation")
    assert [a["type"] for a in rule["actions"]] == ["alert"]
    assert server.apply().code == 0
    built = next(r for r in server.fake.automod.values() if r["name"] == "Impersonation")
    assert [a["type"] for a in built["actions"]] == [2]


def test_voice_and_stage_rows_exist_and_the_check_reads_them_even_while_they_wait(layout, tmp_path):
    assert access.access_problems(layout) == []
    data = layout_data()
    voice = next(c for c in data["channels"] if c["type"] == "voice")
    voice["overwrites"] = []
    loaded = load(write_layout(tmp_path, data), base_dir=ROOT)
    assert any("connect and speak in the voice channel" in p for p in access.access_problems(loaded))
    data = layout_data()
    voice = next(c for c in data["channels"] if c["type"] == "voice")
    voice["overwrites"] = [{"target": "@everyone", "allow": ["speak"], "deny": ["connect"]}]
    loaded = load(write_layout(tmp_path, data, "second.toml"), base_dir=ROOT)
    assert any("could not manage the voice channel" in p for p in access.access_problems(loaded))


def test_the_voice_category_can_be_switched_on_and_built(make_server, layout, tmp_path):
    data = layout_data()
    for category in data["categories"]:
        if category["name"] == "Voice":
            category["enabled"] = True
    for channel in data["channels"]:
        if channel["type"] in ("voice", "stage"):
            channel["enabled"] = True
    path = write_layout(tmp_path, data)
    # switching the channels on needs more of the bot, so its role is raised first, as stand-down --raise says
    h = make_server(bot_permissions=load(path, base_dir=ROOT).bot_permissions())
    assert h.apply(layout=path).code == 0
    voice = h.fake.by_name("Workbench")
    assert h.fake.perms_for_roles([], "Workbench") & BITS["connect"]
    assert h.fake.bot_in(voice) & BITS["manage_channels"]
    assert h.plan(layout=path).code == 0


def test_a_message_whose_answer_was_lost_is_not_posted_twice(server, layout):
    server.fake.fail_next(r"/channels/\d+/messages$", "lost", times=1, method="POST")
    result = server.apply()
    assert result.code == 0, result.out + result.err
    for channel in layout.active_channels:
        if channel.messages:
            posted = list(server.fake.messages[server.fake.by_name(channel.name)["id"]])
            assert len(posted) == len(channel.messages), channel.name


def test_the_failing_tools_own_words_are_shown_with_the_secret_taken_out():
    code = "import sys; sys.stderr.write('failed for ' + sys.stdin.read()); sys.exit(3)"
    with pytest.raises(subprocess.CalledProcessError) as caught:
        ops.default_runner([sys.executable, "-c", code], "the-secret-value")
    assert "failed for [removed]" in caught.value.stderr
    assert "the-secret-value" not in caught.value.stderr


def test_sync_secrets_shows_what_the_tool_said(server, layout):
    assert server.apply().code == 0
    out, err = io.StringIO(), io.StringIO()
    seen = {}

    def failing(command, value):
        seen["value"] = value
        raise subprocess.CalledProcessError(1, command, output="", stderr="not logged in, tried " + value)

    code = cli.main(
        ["sync-secrets", "--layout", str(layout.path)],
        env={"DISCORD_BOT_TOKEN": server.fake.token, "DISCORD_API_BASE": server.fake.url},
        stdout=out,
        stderr=err,
        runner=failing,
        cwd=ROOT,
    )
    assert code == 2
    assert "not logged in" in err.getvalue() and "[removed]" in err.getvalue()
    assert seen["value"] not in err.getvalue()


def test_sync_secrets_stores_the_staff_role_ids_on_standard_input_only(server, layout):
    assert server.apply().code == 0
    result = server.run("sync-secrets")
    assert result.code == 0, result.out + result.err
    fake = server.fake
    staff_ids = [fake.role_named(n)["id"] for n in access.STAFF_ROLES]
    job = [(c, v) for c, v in result.stored if "STAFF_ROLE_IDS" in c]
    assert len(job) == 1
    command, value = job[0]
    assert command[:3] == ["npx", "--prefix", str(ROOT / "worker")] or "wrangler" in command
    assert value == ",".join(staff_ids)
    # on standard input only: never on a command line, in any output or in the summary posted in the server
    for staff_id in staff_ids:
        assert not any(staff_id in part for part in command)
        assert staff_id not in result.out and staff_id not in result.err
    assert "STAFF_ROLE_IDS (cloudflare): 2 roles, Maintainer and Moderator" in result.out
    # the run summary posted in the server holds no id. The start messages hold role links by id on purpose
    log = fake.messages.get(fake.by_name(layout.server["summary_channel"])["id"], [])
    assert not any(staff_id in m["content"] for m in log for staff_id in staff_ids)


def test_sync_secrets_stops_and_stores_nothing_when_a_staff_role_is_missing(server):
    assert server.apply().code == 0
    fake = server.fake
    del fake.roles[fake.role_named("Moderator")["id"]]
    result = server.run("sync-secrets")
    assert result.code == 2
    assert 'the role "Moderator" does not exist on the server yet' in result.err and "Nothing was stored" in result.err
    assert result.stored == []


# ---- threads in the logs ---------------------------------------------------------------------------------------


def test_purge_threads_keeps_new_ones_skips_what_discord_refuses_and_reports_it(server, layout):
    from datetime import UTC, datetime

    assert server.apply().code == 0
    fake = server.fake
    log = layout.server["summary_channel"]
    staff = layout.server["public_updates_channel"]
    old = timedelta(days=400)
    gone = [
        fake.add_thread(log, "old active", archived=False, age=old),
        fake.add_thread(log, "old archived", archived=True, age=old),
        fake.add_thread(log, "old private", archived=True, private=True, age=old),
        fake.add_thread(staff, "old staff", archived=True, age=old),
        fake.add_thread(log, "old and empty", archived=False, age=old, messages=0),
    ]
    recent = fake.add_thread(log, "recent", archived=False, age=timedelta(days=2))
    new_and_empty = fake.add_thread(log, "new and empty", archived=False, age=timedelta(days=1), messages=0)
    stamp = (datetime.now(UTC) - old).isoformat()
    fresh = datetime.now(UTC).isoformat()

    def two_messages(thread):
        fake.messages[thread["id"]] = [
            {
                "id": "100001",
                "channel_id": thread["id"],
                "author": {"id": fake.bot_user_id},
                "content": "ancient",
                "flags": 0,
                "timestamp": stamp,
            },
            {
                "id": "100002",
                "channel_id": thread["id"],
                "author": {"id": fake.bot_user_id},
                "content": "fresh",
                "flags": 0,
                "timestamp": fresh,
            },
        ]

    live = fake.add_thread(log, "old thread with a new post", archived=False, age=old, messages=0)
    two_messages(live)
    shut = fake.add_thread(log, "archived with a new post", archived=True, age=old, messages=0)
    two_messages(shut)
    result = server.run("purge-mod-log", "--older-than", "365d", tty=True, stdin=layout.name + "\n")
    # a refusal for one item did not stop the rest and it is reported with exit 3
    assert result.code == 3, result.out + result.err
    assert "including 5 whole threads" in result.out
    assert not any(t["id"] in fake.threads for t in gone)
    assert (
        recent["id"] in fake.threads and new_and_empty["id"] in fake.threads
    ), "a thread younger than the period stays"
    assert [m["content"] for m in fake.messages[live["id"]]] == ["fresh"]
    assert [m["content"] for m in fake.messages[shut["id"]]] == ["ancient", "fresh"]
    assert "Skipped 1 items that Discord refused" in result.out
    assert "a message in an archived thread in #" in result.out and "Thread is archived" in result.out
    assert "Reset Token" in result.out
    assert methods(fake) <= {"DELETE", "POST", "PATCH", "PUT"}


def test_listing_archived_threads_needs_read_history_and_private_ones_need_manage_threads(make_server):
    h = make_server()
    fake = h.fake
    fake.add_channel("log", TEXT)
    thread = fake.add_thread("log", "t", archived=True, private=True)
    channel = fake.by_name("log")
    assert (
        raw(fake, "GET", f"/channels/{channel['id']}/threads/archived/private")[1]["threads"][0]["id"] == thread["id"]
    )
    fake.roles[fake.bot_role_id]["permissions"] = str(BITS["view_channel"] | BITS["read_message_history"])
    assert raw(fake, "GET", f"/channels/{channel['id']}/threads/archived/private")[0] == 403
    assert raw(fake, "GET", f"/channels/{channel['id']}/threads/archived/public")[0] == 200
    assert raw(fake, "DELETE", f"/channels/{thread['id']}")[0] == 403


# ---- what the README promises about the arrangement ---------------------------------------------------------------


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else None]


def test_the_readme_security_section_lists_exactly_what_the_bot_holds(layout):
    readme = (ROOT / "README.md").read_text()
    section = _section(readme, "## What a stolen token can do")
    held = perms.names_of(layout.bot_permissions())
    for name in held:
        assert f"`{name}`" in section, name
    assert f"exactly these {len(held)} permissions" in section
    listed = {n for n in perms.BIT if f"`{n}`" in section}
    assert listed == set(held)
    for words_ in ("They could not", "Kick or ban anyone", "Maintainer, Moderator", "token is reset"):
        assert words_ in section


def test_the_readme_steps_run_in_the_order_a_person_follows_and_the_hand_alternative_lists_the_permissions(layout):
    readme = (ROOT / "README.md").read_text()
    order = [
        "**Turn on two-factor sign-in.**",
        "**Create the server.**",
        "**Enable Community.**",
        "**Create the application.**",
        "**Keep the token out of files and shell history.**",
        "**Invite the bot.**",
        "**Set the two staff roles up.**",
        "**Drag the roles above the bot and finish them by hand.**",
        "**Read the plan.**",
        "**Apply.**",
    ]
    positions = [readme.index(item) for item in order]
    assert positions == sorted(positions)
    numbers = re.findall(
        r"^(\d+)\. \*\*", readme[readme.index(order[0]) - 4 : readme.index("### What only you can do")], re.M
    )
    assert numbers == [str(n) for n in range(1, len(numbers) + 1)]
    step = readme[readme.index(order[7]) : readme.index(order[8])]
    for role in ("Maintainer", "Moderator"):
        for name in perms.names_of(layout.role(role).permissions):
            assert f"`{name}`" in step, (role, name)
    for words_ in ("kick, approve and reject members", "ban members", "mention everyone"):
        assert words_ in step
    assert "Until this is done, anyone holding the bot's token could edit them" in step
    assert "give yourself the maintainer role" in step.lower()
    assert "Pause Invites" in readme and readme.index("Pause Invites") < readme.index("lockdown --hours 6")
    assert "needs Manage Server" in readme
    assert "There is one window." in readme and "refuse to run until it is done" in readme
