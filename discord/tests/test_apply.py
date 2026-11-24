"""Applying a layout: the first build, the second run and what happens around them."""

from __future__ import annotations

import re

import pytest
from conftest import words
from helpers import actual_rows, deletes, expected_rows, methods, only_words

from serverkit import perms

CHANGE_WORDS = ("create", "update", "delete", "rename", "rotate")


def test_a_new_server_is_built_exactly_as_the_layout_says(server, layout):
    result = server.apply()
    assert result.code == 0, result.out + result.err
    fake = server.fake

    for role in layout.roles:
        built = fake.role_named(role.name)
        assert int(built["permissions"]) == role.permissions, role.name
        assert built["hoist"] is role.hoist
        assert built["mentionable"] is role.mentionable
        assert built["color"] == role.colour
    assert int(fake.roles[fake.guild_id]["permissions"]) == layout.everyone
    # the owner's roles sit above the bot's own and the roles the script manages below it, in layout order
    bot = fake.roles[fake.bot_role_id]["position"]
    positions = [fake.role_named(r.name)["position"] for r in layout.roles]
    assert positions == sorted(positions, reverse=True)
    assert all((p > bot) == r.owner for p, r in zip(positions, layout.roles, strict=True))

    for category in layout.active_categories:
        built = fake.by_name(category.name, 4)
        assert actual_rows(built) == expected_rows(fake, category.overwrites)
    for channel in layout.active_channels:
        built = fake.by_name(channel.name)
        assert built["type"] == channel.type_id, channel.name
        parent = fake.channels[built["parent_id"]]["name"] if built["parent_id"] else None
        assert parent == channel.category
        if channel.type in ("text", "announcement", "forum"):
            assert (built["topic"] or "") == channel.topic, channel.name
        assert actual_rows(built) == expected_rows(fake, channel.overwrites), channel.name
        if channel.type == "text":
            assert built["rate_limit_per_user"] == channel.slow_mode
    for channel in layout.channels:
        if not layout.channel_active(channel):
            assert not [c for c in fake.channels.values() if c["name"].lower() == channel.name.lower()], channel.name


def test_forums_get_their_tags_and_settings(server, layout):
    assert server.apply().code == 0
    for channel in layout.active_channels:
        if channel.type != "forum":
            continue
        built = server.fake.by_name(channel.name)
        forum = channel.forum
        assert [t["name"] for t in built["available_tags"]] == [t["name"] for t in forum["tags"]]
        assert [t["moderated"] for t in built["available_tags"]] == [t["moderated"] for t in forum["tags"]]
        assert bool(built["flags"] & (1 << 4)) is forum["require_tag"]
        assert built["rate_limit_per_user"] == forum["post_slow_mode"]
        assert built["default_forum_layout"] == 1
        assert built["default_auto_archive_duration"] == forum["auto_archive_minutes"]


def test_server_settings_are_set_and_point_at_the_right_channels(server, layout):
    assert server.apply().code == 0
    guild = server.fake.guild
    s = layout.server
    assert guild["verification_level"] == s["verification_level"]
    assert guild["explicit_content_filter"] == s["explicit_content_filter"]
    assert guild["default_message_notifications"] == s["default_message_notifications"]
    assert guild["preferred_locale"] == s["preferred_locale"]
    assert guild["system_channel_flags"] == s["system_channel_flags"]
    assert guild["system_channel_id"] == server.fake.by_name(s["system_channel"])["id"]
    assert guild["rules_channel_id"] == server.fake.by_name(s["rules_channel"])["id"]
    assert guild["public_updates_channel_id"] == server.fake.by_name(s["public_updates_channel"])["id"]
    assert guild["safety_alerts_channel_id"] == server.fake.by_name(s["safety_alerts_channel"])["id"]
    # the script never asks for the Community switch, which needs Administrator
    assert not any("features" in str(r) for r in server.fake.requests)


def test_auto_moderation_onboarding_webhooks_and_commands_exist(server, layout):
    assert server.apply().code == 0
    fake = server.fake
    assert sorted(r["name"] for r in fake.automod.values()) == sorted(r["name"] for r in layout.automod)
    alert = next(r for r in fake.automod.values() if r["name"] == "Spam")
    assert {a["type"] for a in alert["actions"]} == {1, 2}
    secrets = next(r for r in fake.automod.values() if r["name"] == "Secrets")
    assert len(secrets["trigger_metadata"]["regex_patterns"]) == 8
    assert all(a["type"] == 1 for a in secrets["actions"])
    onboarding = fake.onboarding
    assert onboarding["enabled"] is True
    assert sorted(fake.channels[c]["name"] for c in onboarding["default_channel_ids"]) == sorted(
        layout.onboarding["default_channels"]
    )
    prompt = onboarding["prompts"][0]
    assert [o["title"] for o in prompt["options"]] == [o["title"] for o in layout.onboarding["prompts"][0]["options"]]
    first = prompt["options"][0]
    assert [fake.roles[r]["name"] for r in first["role_ids"]] == layout.onboarding["prompts"][0]["options"][0]["roles"]
    active = [h for h in layout.webhooks if layout.channel_active(layout.channel(h["channel"]))]
    assert sorted(h["name"] for h in fake.webhooks.values()) == sorted(h["name"] for h in active)
    assert all(h["application_id"] == fake.app_id for h in fake.webhooks.values())
    assert {c["name"] for c in fake.commands} >= {"help", "docs", "report", "mod"}
    assert ("status" in {c["name"] for c in fake.commands}) == bool(layout.status.get("enabled"))


def test_the_texts_are_posted_with_links_filled_in_and_nothing_pings(server, layout):
    assert server.apply().code == 0
    fake = server.fake
    for channel in layout.active_channels:
        if not channel.messages:
            continue
        posted = sorted(
            (m for m in fake.messages[fake.by_name(channel.name)["id"]] if m.get("type", 0) == 0),
            key=lambda m: int(m["id"]),
        )
        assert len(posted) == len(channel.messages)
        for message, source in zip(posted, channel.messages, strict=True):
            text = message["content"] + " ".join(
                e.get("title", "") + e.get("description", "") for e in message["embeds"]
            )
            assert "{channel:" not in text and "{role:" not in text and "{command:" not in text and "{nav:" not in text
            assert len(message["content"]) <= 2000
            # no post or edit may ping, a role link included
            assert message["allowed_mentions"] == {"parse": []}
            if channel.style == "plain":
                assert message["flags"] & 4, "link previews are switched off"
                assert not message["embeds"]
            else:
                assert message["flags"] == 0 and message["embeds"] and not message["content"]
            if "{channel:" in source:
                assert re.search(r"<#\d+>", text)
            if "{nav:customize}" in source:
                assert "<id:customize>" in text


def test_every_change_carries_an_audit_log_reason_with_the_layout_hash(server, layout):
    assert server.apply().code == 0
    fake = server.fake
    assert len(fake.audit) == fake.write_count > 50
    prefix = f"{layout.name} layout {layout.hash8}: "
    assert all(entry["reason"].startswith(prefix) for entry in fake.audit), [
        e for e in fake.audit if not e["reason"].startswith(prefix)
    ][:3]
    assert all(len(entry["reason"]) <= 512 for entry in fake.audit)


def test_plan_never_writes(server):
    before = server.fake.state()
    result = server.plan()
    assert result.code == 4
    assert methods(server.fake) == set()
    assert server.fake.state() == before


def test_plan_shows_the_words_the_readme_explains(server, layout):
    out = server.plan().out
    found = {w for w, _ in words(out)}
    assert {"ok", "create", "update"} <= found
    # the project layouts now open every channel at once, so "deferred" shows only when a layout holds one back
    if any(not ch.enabled for ch in layout.channels):
        assert "deferred" in found
    assert "Mode: plan. Nothing is changed." in out
    assert any(line.startswith("Summary: ") for line in out.splitlines())


def test_plan_after_apply_shows_no_change_and_sends_nothing(server):
    assert server.apply().code == 0
    server.fake.requests.clear()
    result = server.plan()
    assert result.code == 0
    assert not only_words(result.out, *CHANGE_WORDS, "blocked")
    assert result.out.rstrip().splitlines()[-1].startswith("Summary: nothing to change")
    assert methods(server.fake) == set()


def test_a_second_apply_sends_no_write_at_all(server):
    assert server.apply().code == 0
    before = server.fake.state()
    count = server.fake.write_count
    again = server.apply()
    assert again.code == 0, again.out + again.err
    assert server.fake.write_count == count
    assert server.fake.state() == before
    assert "Applied 0 changes." in again.out


def test_the_summary_is_posted_once_and_carries_no_id(server, layout):
    assert server.apply().code == 0
    fake = server.fake
    log = fake.messages[fake.by_name(layout.server["summary_channel"])["id"]]
    assert len(log) == 1
    assert layout.hash8 in log[0]["content"]
    assert not re.search(r"\d{17,20}", log[0]["content"])
    assert log[0]["flags"] & 4
    server.apply()
    assert len(fake.messages[fake.by_name(layout.server["summary_channel"])["id"]]) == 1


def test_no_summary_flag(server, layout):
    assert server.apply("--no-summary").code == 0
    fake = server.fake
    assert not fake.messages.get(fake.by_name(layout.server["summary_channel"])["id"])


def test_plain_apply_never_deletes_or_renames(server):
    server.apply()
    server.fake.add_channel("someone-made-this", 0)
    server.fake.add_role("Someone made this", 0, position=2)
    server.apply()
    assert deletes(server.fake) == []


def test_community_off_builds_what_it_can_and_exits_3(make_server, layout):
    h = make_server(community=False)
    result = h.apply()
    assert result.code == 3, result.out + result.err
    fake = h.fake
    assert "Enable Community in the server settings, then run this again." in result.out
    names = {c["name"] for c in fake.channels.values()}
    assert {"general", "help", "mod-log"} <= names
    for channel in layout.active_channels:
        if channel.type == "announcement":
            assert channel.name not in names
    assert fake.onboarding["enabled"] is False and not fake.onboarding["prompts"]
    assert fake.guild["rules_channel_id"] is None
    assert any(w == "blocked" for w, _ in words(result.out))
    # the owner switches Community on and runs it again. That finishes the job
    fake.make_community(wizard_channels=False)
    again = h.apply()
    assert again.code == 0, again.out + again.err
    assert h.plan().code == 0


def test_a_missing_news_feature_blocks_announcement_channels(make_server, layout):
    h = make_server(news_with_community=False)
    result = h.apply()
    assert result.code == 3, result.out
    assert "NEWS" in result.out
    assert not [c for c in h.fake.channels.values() if c["type"] == 5]


def test_forums_that_need_community_are_blocked_not_fatal(make_server):
    h = make_server(community=False, forums_need_community=True)
    result = h.apply()
    assert result.code == 3, result.out + result.err
    assert not [c for c in h.fake.channels.values() if c["type"] == 15]
    assert "Community" in result.out
    h.fake.make_community(wizard_channels=False)
    assert h.apply().code == 0
    assert h.plan().code == 0


def test_onboarding_is_enabled_when_forums_do_not_count(make_server, layout):
    h = make_server(forums_count_for_onboarding=False)
    result = h.apply()
    assert result.code == 0, result.out + result.err
    assert h.fake.onboarding["enabled"] is True


def test_an_onboarding_refusal_prints_discords_own_field_detail(make_server, layout):
    # Discord may count differently from the documentation: here it wants six channels that everyone can write in
    h = make_server(onboarding_needs_postable=6)
    result = h.apply()
    assert result.code == 1, result.out + result.err
    assert "default_channel_ids: ONBOARDING_CONSTRAINTS: There must be at least 7 Default Channels" in result.out
    assert "Invalid Form Body" in result.out


def test_wizard_channels_visible_to_the_bot_are_adopted_not_duplicated(make_server, layout):
    h = make_server(community=False)
    h.fake.make_community(wizard_channels=True, wizard_visible_to_bot=True)
    rules_id = h.fake.by_name("rules")["id"]
    updates_id = h.fake.by_name("moderator-only")["id"]
    assert h.fake.by_name("rules")["parent_id"] is None
    result = h.apply()
    assert result.code == 0, result.out + result.err
    fake = h.fake
    assert [c for c in fake.channels.values() if c["name"] == "rules"] == [fake.channels[rules_id]]
    assert [c for c in fake.channels.values() if c["name"] == "moderator-only"] == [fake.channels[updates_id]]
    assert fake.channels[rules_id]["parent_id"] == fake.by_name("Start here", 4)["id"]
    assert fake.guild["rules_channel_id"] == rules_id
    assert h.plan().code == 0


def test_a_wizard_channel_the_bot_cannot_see_is_never_found_so_a_second_is_made(make_server, layout):
    h = make_server(community=False)
    h.fake.make_community(wizard_channels=True, wizard_visible_to_bot=False)
    hidden_id = h.fake.by_name("moderator-only")["id"]
    result = h.apply()
    # Discord points the updates channel at its own private one, which the bot cannot change: an owner step
    assert result.code == 3, result.out + result.err
    assert (
        'In Server Settings, Community, Overview, set "Community updates channel" to the #moderator-only under Staff'
        in result.out
    )
    named = [c for c in h.fake.channels.values() if c["name"] == "moderator-only"]
    assert len(named) == 2 and hidden_id in {c["id"] for c in named}
    assert h.fake.guild["public_updates_channel_id"] == hidden_id
    # the owner makes the change by hand and a further run settles without making more
    h.fake.guild["public_updates_channel_id"] = (
        h.fake.by_name("moderator-only", 0)["id"] if False else next(c["id"] for c in named if c["id"] != hidden_id)
    )
    h.fake.guild["safety_alerts_channel_id"] = h.fake.guild["public_updates_channel_id"]
    assert h.apply().code == 0
    assert len([c for c in h.fake.channels.values() if c["name"] == "moderator-only"]) == 2


def test_a_text_channel_becomes_an_announcement_channel(server, layout):
    fake = server.fake
    fake.add_channel("announcements", 0)
    result = server.apply()
    assert result.code == 0, result.out + result.err
    assert fake.by_name("announcements")["type"] == 5


def test_a_channel_of_another_kind_is_a_conflict_that_changes_nothing(server):
    fake = server.fake
    fake.add_channel("help", 0)
    before = fake.state()
    result = server.apply()
    assert result.code == 2
    assert "help" in result.err and "different kind of channel" in result.err
    assert fake.state() == before
    assert methods(fake) == set()
    assert server.plan().code == 2


def test_a_channel_in_the_wrong_category_is_moved_and_that_is_an_update(server, layout):
    assert server.apply().code == 0
    fake = server.fake
    fake.by_name("general")["parent_id"] = fake.by_name("Support", 4)["id"]
    plan = server.plan()
    assert plan.code == 4
    assert any("general" in t and "move to" in t for w, t in words(plan.out) if w == "update")
    assert server.apply().code == 0
    assert fake.channels[fake.by_name("general")["parent_id"]]["name"] == "Community"


def test_unmanaged_things_are_reported_and_left_alone(server, layout):
    assert server.apply().code == 0
    fake = server.fake
    fake.add_channel("random", 0, parent="Community")
    old = fake.add_role("Old helpers", 0, position=2)
    fake.add_channel("Archive", 4)
    hook = {
        "id": "9" * 5,
        "type": 1,
        "channel_id": fake.by_name("general")["id"],
        "name": "Manual hook",
        "application_id": None,
        "guild_id": fake.guild_id,
        "token": "t",
        "url": "http://127.0.0.1/x",
    }
    fake.webhooks[hook["id"]] = hook
    fake.add_message(layout.channels[0].name, "hand written note by the bot")
    # a hand-added overwrite on a Staff channel may be a leak
    staff = fake.by_name("mod-log")
    staff["permission_overwrites"].append(
        {"id": old["id"], "type": 0, "allow": str(perms.BIT["view_channel"]), "deny": "0"}
    )
    # and a drift on the same channel so that it is written to
    staff["topic"] = "changed by hand"
    before_names = {c["name"] for c in fake.channels.values()}

    plan = server.plan()
    assert plan.code == 4
    unmanaged = [t for w, t in words(plan.out) if w == "unmanaged"]
    assert any("#random" in t for t in unmanaged)
    assert any('role "Old helpers"' in t for t in unmanaged)
    assert any('category "Archive"' in t for t in unmanaged)
    assert any("Manual hook" in t for t in unmanaged)
    warnings = [t for w, t in words(plan.out) if w == "warning"]
    assert any("mod-log" in t and "Old helpers" in t for t in warnings), plan.out

    result = server.apply()
    assert result.code == 0, result.out + result.err
    assert deletes(fake) == []
    assert {c["name"] for c in fake.channels.values()} >= before_names
    assert old["id"] in fake.roles and hook["id"] in fake.webhooks
    # the topic was put back and the unmanaged row survived the write
    assert fake.by_name("mod-log")["topic"] != "changed by hand"
    assert any(o["id"] == old["id"] for o in fake.by_name("mod-log")["permission_overwrites"])
    # nothing more to do: the extras stay in the plan as notes and do not make a change
    after = server.plan()
    assert after.code == 0
    assert not only_words(after.out, *CHANGE_WORDS)


def test_drift_is_found_named_and_put_back(server, layout):
    assert server.apply().code == 0
    fake = server.fake
    fake.guild["verification_level"] = 0
    fake.by_name("general")["topic"] = "hand edited"
    contributor = fake.role_named("Contributor")
    contributor["permissions"] = str(perms.BIT["add_reactions"])
    contributor["hoist"] = False
    first_announcement = next(c for c in layout.active_channels if c.type == "announcement")
    ann = fake.by_name(first_announcement.name)
    for row in ann["permission_overwrites"]:
        if row["id"] == fake.guild_id:
            row["deny"] = "0"
    help_forum = fake.by_name("help")
    help_forum["available_tags"] = [t for t in help_forum["available_tags"] if t["name"] != "Solved"]
    spam = next(r for r in fake.automod.values() if r["name"] == "Spam")
    spam["actions"] = [a for a in spam["actions"] if a["type"] != 2]
    fake.automod[spam["id"]] = spam
    rules_channel = next(c for c in layout.active_channels if c.name == layout.server["rules_channel"])
    msg = fake.messages[fake.by_name(rules_channel.name)["id"]][0]
    msg["content"] = "edited by hand"

    plan = server.plan()
    assert plan.code == 4
    updates = " | ".join(t for w, t in words(plan.out) if w == "update")
    for needle in (
        "verification level",
        "general: topic",
        "Contributor: permissions",
        "hoist",
        "overwrites",
        "tags",
        '"Spam"',
        "message 1",
    ):
        assert needle in updates, (needle, plan.out)
    assert server.apply().code == 0
    assert fake.guild["verification_level"] == layout.server["verification_level"]
    assert int(fake.role_named("Contributor")["permissions"]) == 0
    assert any(t["name"] == "Solved" for t in fake.by_name("help")["available_tags"])
    assert server.plan().code == 0


def test_a_tag_keeps_its_id_when_the_forum_is_updated(server):
    assert server.apply().code == 0
    forum = server.fake.by_name("help")
    ids = {t["name"]: t["id"] for t in forum["available_tags"]}
    forum["topic"] = "changed"
    assert server.apply().code == 0
    assert {t["name"]: t["id"] for t in server.fake.by_name("help")["available_tags"]} == ids


@pytest.mark.parametrize("flag", ["--only", None])
def test_only_limits_the_run_to_named_steps(server, flag):
    result = server.apply("--only", "roles") if flag else server.apply()
    assert result.code in (0, 3)
    if flag:
        assert not server.fake.channels
        assert any(r["name"] != "@everyone" and not r["managed"] for r in server.fake.roles.values())
        assert not [t for w, t in words(result.out) if w == "create" and t.startswith("#")]


def test_only_rejects_an_unknown_step(server):
    result = server.plan("--only", "roles,nonsense")
    assert result.code == 2 and "nonsense" in result.err


def test_json_format_carries_the_same_plan(server):
    import json

    result = server.plan("--format", "json")
    data = json.loads(result.out)
    assert data["exit_code"] == result.code == 4
    assert data["mode"] == "plan"
    assert any(c["word"] == "create" and c["section"] == "Roles" for c in data["changes"])
    assert data["summary"].startswith("Summary:")


def test_colour_is_off_unless_asked_for_and_no_color_wins(server):
    plain = server.plan().out
    assert "\x1b[" not in plain
    # NO_COLOR is set by the harness, so asking for colour still gives none
    assert "\x1b[" not in server.run("plan", "--colour").out
    assert "\x1b[" in server.run("plan", "--colour", env={"NO_COLOR": None}).out


def test_the_plan_carries_no_id_token_or_address(server):
    out = server.plan().out + server.apply().out
    assert not re.search(r"\d{17,20}", out)
    assert server.fake.token not in out
    assert "webhooks/" not in out
