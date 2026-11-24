"""For each rule the fake enforces: the fake refuses it and the script copes with the refusal."""

from __future__ import annotations

import json
import urllib.request

import pytest
from conftest import words
from fake_discord import ANNOUNCEMENT, BITS, FORUM, STAGE, TEXT, FakeDiscord
from helpers import methods, raw

from serverkit import perms


@pytest.fixture
def fake(make_server) -> FakeDiscord:
    # the bot starts with almost nothing, so each test gives it exactly what the rule in question needs
    start = perms.to_int(["view_channel", "send_messages", "read_message_history"])
    return make_server(community=False, bot_permissions=start).fake


def gid(fake):
    return fake.guild_id


def give_bot(fake, *names):
    role = fake.roles[fake.bot_role_id]
    role["permissions"] = str(int(role["permissions"]) | sum(BITS[n] for n in names))


# ---- the connection ------------------------------------------------------------------------------


def test_no_token_or_a_wrong_token_is_401(fake):
    assert raw(fake, "GET", "/users/@me", token="wrong")[0] == 401
    request = urllib.request.Request(fake.url + "/users/@me")
    request.add_header("User-Agent", "DiscordBot (https://example.org, 1.0)")
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(request, timeout=5)
    assert err.value.code == 401


def test_the_script_stops_at_once_on_a_refused_token(make_server):
    h = make_server()
    result = h.run("plan", env={"DISCORD_BOT_TOKEN": "not-the-token"})
    assert result.code == 2
    assert "refused the token" in result.err
    assert "not-the-token" not in result.err + result.out
    assert methods(h.fake) == set()


def test_a_request_without_the_documented_user_agent_or_json_type_is_refused(fake):
    assert raw(fake, "GET", "/users/@me", headers={"User-Agent": "python"})[0] == 403
    status, _ = raw(
        fake, "PATCH", f"/guilds/{gid(fake)}", {"verification_level": 1}, headers={"Content-Type": "text/plain"}
    )
    assert status == 400


def test_the_script_sends_the_documented_user_agent_and_content_type_on_every_request(make_server):
    h = make_server()
    assert h.apply().code == 0
    # a single request in the wrong form would have been refused and the run would have failed
    assert h.fake.write_count > 50


# ---- permissions ---------------------------------------------------------------------------------


def test_a_bot_can_only_grant_permissions_it_holds(fake):
    give_bot(fake, "manage_roles")
    status, body = raw(
        fake, "POST", f"/guilds/{gid(fake)}/roles", {"name": "X", "permissions": str(BITS["kick_members"])}
    )
    assert status == 403, body
    give_bot(fake, "kick_members")
    assert (
        raw(fake, "POST", f"/guilds/{gid(fake)}/roles", {"name": "X", "permissions": str(BITS["kick_members"])})[0]
        == 200
    )


def test_the_script_names_every_permission_the_bot_lacks_and_sends_no_write(make_server, layout):
    held = layout.bot_permissions() & ~perms.to_int(["moderate_members", "manage_threads", "manage_messages"])
    h = make_server(bot_permissions=held)
    result = h.apply()
    assert result.code == 2
    assert "moderate_members" in result.out and "manage_threads" in result.out and "manage_messages" in result.out
    assert "serverkit invite-url" in result.out
    assert methods(h.fake) == set()
    assert h.plan().code == 2


def test_a_bot_can_only_edit_roles_below_its_own(fake):
    give_bot(fake, "manage_roles")
    above = fake.add_role("Above", 0, position=5)
    below = fake.add_role("Below", 0, position=1)
    fake.roles[fake.bot_role_id]["position"] = 3
    assert raw(fake, "PATCH", f"/guilds/{gid(fake)}/roles/{above['id']}", {"hoist": True})[0] == 403
    assert raw(fake, "PATCH", f"/guilds/{gid(fake)}/roles/{below['id']}", {"hoist": True})[0] == 200
    assert raw(fake, "PATCH", f"/guilds/{gid(fake)}/roles", [{"id": above["id"], "position": 1}])[0] == 403
    assert raw(fake, "DELETE", f"/guilds/{gid(fake)}/roles/{above['id']}")[0] == 403
    assert raw(fake, "PATCH", f"/guilds/{gid(fake)}/roles/{fake.bot_role_id}", {"hoist": True})[0] == 403


def test_the_script_stops_with_instructions_when_the_bots_role_is_below_a_role_it_manages(make_server, layout):
    h = make_server()
    fake = h.fake
    below = fake.add_role("Contributor", 0, position=2)
    fake.roles[fake.bot_role_id]["position"] = 1
    before = fake.state()
    result = h.apply()
    assert result.code == 2
    assert "drag the bot's role above them" in result.out and "Contributor" in result.out
    assert fake.state() == before and below["id"] in fake.roles


def test_the_script_stops_when_the_bots_role_sits_above_the_owners_roles(make_server, layout):
    h = make_server()
    fake = h.fake
    fake.roles[fake.bot_role_id]["position"] = 50
    before = fake.state()
    result = h.apply()
    assert result.code == 2
    assert "drag them above the bot's role" in result.out and "Maintainer" in result.out
    assert fake.state() == before


def test_the_script_refuses_to_run_when_its_own_role_holds_administrator(make_server):
    h = make_server()
    fake = h.fake
    give_bot(fake, "administrator")
    result = h.apply()
    assert result.code == 2
    assert "Administrator" in result.out
    assert methods(fake) == set()
    assert h.plan().code == 2 and h.run("plan").code == 2


def test_the_script_refuses_when_another_role_the_bot_holds_has_administrator(make_server):
    h = make_server()
    fake = h.fake
    extra = fake.add_role("Old admin", BITS["administrator"], position=1)
    fake.bot_member_roles.append(extra["id"])
    result = h.apply()
    assert result.code == 2 and "Old admin" in result.out
    assert methods(fake) == set()


def test_an_overwrite_can_only_use_permissions_the_bot_holds_and_manage_roles_needs_administrator(fake):
    give_bot(fake, "manage_channels", "manage_roles")
    row = {"id": gid(fake), "type": 0, "allow": "0", "deny": str(BITS["kick_members"])}
    assert (
        raw(fake, "POST", f"/guilds/{gid(fake)}/channels", {"name": "a", "type": 0, "permission_overwrites": [row]})[0]
        == 403
    )
    row = {"id": gid(fake), "type": 0, "allow": str(BITS["manage_roles"]), "deny": "0"}
    assert (
        raw(fake, "POST", f"/guilds/{gid(fake)}/channels", {"name": "a", "type": 0, "permission_overwrites": [row]})[0]
        == 403
    )


def test_the_channel_list_leaves_out_what_the_bot_cannot_view(fake):
    hidden = [{"id": gid(fake), "type": 0, "allow": "0", "deny": str(BITS["view_channel"])}]
    fake.add_channel("secret", TEXT, overwrites=hidden)
    fake.add_channel("open", TEXT)
    status, listing = raw(fake, "GET", f"/guilds/{gid(fake)}/channels")
    assert [c["name"] for c in listing] == ["open"]
    status, _ = raw(fake, "GET", f"/channels/{fake.by_name('secret')['id']}")
    assert status == 404


def test_turning_community_on_or_off_needs_administrator_and_the_script_never_asks(fake):
    status, _ = raw(fake, "PATCH", f"/guilds/{gid(fake)}", {"features": ["COMMUNITY"]})
    assert status == 403


# ---- channel kinds -------------------------------------------------------------------------------


def test_announcement_and_stage_channels_need_community(fake):
    give_bot(fake, "manage_channels")
    assert raw(fake, "POST", f"/guilds/{gid(fake)}/channels", {"name": "news", "type": ANNOUNCEMENT})[0] == 400
    assert raw(fake, "POST", f"/guilds/{gid(fake)}/channels", {"name": "hall", "type": STAGE})[0] == 400
    fake.make_community(wizard_channels=False)
    assert raw(fake, "POST", f"/guilds/{gid(fake)}/channels", {"name": "news", "type": ANNOUNCEMENT})[0] == 200
    fake.news_with_community = False
    fake.guild["features"] = ["COMMUNITY"]
    assert raw(fake, "POST", f"/guilds/{gid(fake)}/channels", {"name": "news2", "type": ANNOUNCEMENT})[0] == 400


def test_forums_need_community_only_behind_the_switch(fake):
    give_bot(fake, "manage_channels")
    assert raw(fake, "POST", f"/guilds/{gid(fake)}/channels", {"name": "f1", "type": FORUM})[0] == 200
    fake.forums_need_community = True
    assert raw(fake, "POST", f"/guilds/{gid(fake)}/channels", {"name": "f2", "type": FORUM})[0] == 400


def test_only_text_and_announcement_convert_into_each_other(fake):
    give_bot(fake, "manage_channels")
    fake.make_community(wizard_channels=False)
    text = fake.add_channel("t", TEXT)
    forum = fake.add_channel("f", FORUM)
    assert raw(fake, "PATCH", f"/channels/{text['id']}", {"type": FORUM})[0] == 400
    assert raw(fake, "PATCH", f"/channels/{forum['id']}", {"type": TEXT})[0] == 400
    assert raw(fake, "PATCH", f"/channels/{text['id']}", {"type": ANNOUNCEMENT})[0] == 200


def test_the_rules_and_updates_channels_of_a_community_server_cannot_be_deleted(make_server):
    h = make_server(community=False)
    fake = h.fake
    give_bot(fake, "manage_channels")
    fake.make_community(wizard_channels=True, wizard_visible_to_bot=True)
    status, body = raw(fake, "DELETE", f"/channels/{fake.by_name('rules')['id']}")
    assert status == 400 and body["code"] == 50074


def test_prune_channels_does_not_try_to_delete_the_rules_or_updates_channel(make_server, layout):
    h = make_server(community=False)
    fake = h.fake
    fake.make_community(wizard_channels=True, wizard_visible_to_bot=True)
    assert h.apply().code == 0
    # a person's channel becomes the rules channel. The script would delete it under --prune, so it must not
    mine = fake.add_channel("our-news", TEXT)
    fake.guild["rules_channel_id"] = mine["id"]
    plan = h.plan("--prune", "channels")
    assert any("cannot be deleted" in t for _w, t in words(plan.out))
    assert not [t for w, t in words(plan.out) if w == "delete" and "our-news" in t]


# ---- limits ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x" * 101},
        {"name": "ok", "topic": "t" * 1025},
        {"name": "ok", "rate_limit_per_user": 21601},
        {"name": "ok", "type": 99},
    ],
)
def test_channel_limits(fake, body):
    give_bot(fake, "manage_channels")
    assert raw(fake, "POST", f"/guilds/{gid(fake)}/channels", {"type": 0, **body})[0] == 400


def test_forum_limits(fake):
    give_bot(fake, "manage_channels")
    base = {"type": FORUM, "name": "f"}
    assert raw(fake, "POST", f"/guilds/{gid(fake)}/channels", {**base, "topic": "t" * 4097})[0] == 400
    assert raw(fake, "POST", f"/guilds/{gid(fake)}/channels", {**base, "topic": "t" * 4096})[0] == 200
    tags = [{"name": f"t{i}"} for i in range(21)]
    assert raw(fake, "POST", f"/guilds/{gid(fake)}/channels", {**base, "name": "g", "available_tags": tags})[0] == 400
    assert (
        raw(
            fake, "POST", f"/guilds/{gid(fake)}/channels", {**base, "name": "h", "available_tags": [{"name": "n" * 21}]}
        )[0]
        == 400
    )


def test_a_category_holds_at_most_fifty_channels_and_the_script_reports_it(make_server, layout):
    h = make_server()
    fake = h.fake
    fake.add_channel("Community", 4)
    for i in range(50):
        fake.add_channel(f"filler-{i}", TEXT, parent="Community")
    result = h.apply()
    assert result.code == 1
    assert "at most 50" in result.out
    assert "Run it again to resume" in result.out
    assert not any(c["name"] == "general" for c in fake.channels.values())


def test_auto_moderation_limits(fake):
    give_bot(fake, "manage_guild", "moderate_members")
    fake.make_community(wizard_channels=False)
    url = f"/guilds/{gid(fake)}/auto-moderation/rules"
    alert = {"type": 1, "metadata": {}}
    spam = {"name": "a", "event_type": 1, "trigger_type": 3, "actions": [alert]}
    assert raw(fake, "POST", url, spam)[0] == 200
    assert raw(fake, "POST", url, {**spam, "name": "b"})[0] == 400  # one spam rule only
    keyword = {
        "name": "k",
        "event_type": 1,
        "trigger_type": 1,
        "trigger_metadata": {"keyword_filter": ["x"]},
        "actions": [alert],
    }
    for i in range(6):
        assert raw(fake, "POST", url, {**keyword, "name": f"k{i}"})[0] == 200
    assert raw(fake, "POST", url, {**keyword, "name": "k7"})[0] == 400  # six keyword rules
    timeout = {"type": 3, "metadata": {"duration_seconds": 60}}
    assert (
        raw(
            fake,
            "POST",
            url,
            {
                "name": "t",
                "event_type": 1,
                "trigger_type": 4,
                "trigger_metadata": {"presets": [1]},
                "actions": [timeout],
            },
        )[0]
        == 400
    )
    long_message = {"type": 1, "metadata": {"custom_message": "m" * 151}}
    assert raw(fake, "POST", url, {**keyword, "name": "m", "actions": [long_message]})[0] == 400
    assert (
        raw(fake, "POST", url, {**keyword, "name": "w", "trigger_metadata": {"keyword_filter": ["w" * 61]}})[0] == 400
    )
    assert (
        raw(fake, "POST", url, {**keyword, "name": "p", "trigger_metadata": {"regex_patterns": ["a"] * 11}})[0] == 400
    )


def test_a_timeout_action_needs_the_moderate_members_permission(fake):
    give_bot(fake, "manage_guild")
    fake.roles[fake.bot_role_id]["permissions"] = str(
        int(fake.roles[fake.bot_role_id]["permissions"]) & ~BITS["moderate_members"]
    )
    url = f"/guilds/{gid(fake)}/auto-moderation/rules"
    body = {
        "name": "t",
        "event_type": 1,
        "trigger_type": 1,
        "trigger_metadata": {"keyword_filter": ["x"]},
        "actions": [{"type": 3, "metadata": {"duration_seconds": 60}}],
    }
    assert raw(fake, "POST", url, body)[0] == 403


def test_the_script_reports_a_refused_auto_moderation_rule_and_stops_cleanly(make_server):
    h = make_server()
    fake = h.fake
    alert = {"type": 1, "metadata": {}}
    fake.automod["1"] = {
        "id": "1",
        "name": "Old spam",
        "event_type": 1,
        "trigger_type": 3,
        "trigger_metadata": {},
        "actions": [alert],
        "enabled": True,
        "exempt_roles": [],
        "exempt_channels": [],
    }
    result = h.apply()
    assert result.code == 1
    assert "auto-moderation" in result.out and "Maximum number of rules" in result.out
    assert "Run it again to resume" in result.out
    # the person's rule was left alone and what came before the refusal stays built
    assert "1" in fake.automod and fake.by_name("general")


def test_onboarding_needs_seven_default_channels_and_five_that_everyone_can_post_in(fake):
    give_bot(fake, "manage_guild", "manage_roles")
    fake.make_community(wizard_channels=False)
    channels = [fake.add_channel(f"c{i}", TEXT)["id"] for i in range(7)]
    url = f"/guilds/{gid(fake)}/onboarding"
    status, body = raw(fake, "PUT", url, {"prompts": [], "default_channel_ids": channels[:6], "enabled": True})
    assert status == 400 and body["errors"]["default_channel_ids"]["_errors"][0]["code"] == "ONBOARDING_CONSTRAINTS"
    read_only = [{"id": gid(fake), "type": 0, "allow": "0", "deny": str(BITS["send_messages"])}]
    for name in ("c0", "c1", "c2"):
        fake.by_name(name)["permission_overwrites"] = read_only
    assert raw(fake, "PUT", url, {"prompts": [], "default_channel_ids": channels, "enabled": True})[1]["code"] == 50035
    # the minimums hold whenever default channels are sent, as the first live apply showed
    assert raw(fake, "PUT", url, {"prompts": [], "default_channel_ids": channels, "enabled": False})[0] == 400
    assert raw(fake, "PUT", url, {"prompts": [], "default_channel_ids": [], "enabled": False})[0] == 200


def test_webhook_names_cannot_hold_discord_or_clyde(fake):
    give_bot(fake, "manage_webhooks")
    channel = fake.add_channel("c", TEXT)
    url = f"/channels/{channel['id']}/webhooks"
    for name in ("My Discord hook", "clyde", "DISCORDant"):
        assert raw(fake, "POST", url, {"name": name})[0] == 400
    assert raw(fake, "POST", url, {"name": "Fine"})[0] == 200
    assert raw(fake, "POST", url, {"name": "n" * 81})[0] == 400


def test_command_limits(fake):
    url = f"/applications/{fake.app_id}/guilds/{gid(fake)}/commands"
    good = {"name": "ok", "description": "fine", "type": 1}
    assert raw(fake, "PUT", url, [good])[0] == 200
    assert raw(fake, "PUT", url, [{**good, "name": "Upper"}])[0] == 400
    assert raw(fake, "PUT", url, [{**good, "description": ""}])[0] == 400
    assert raw(fake, "PUT", url, [{**good, "description": "d" * 101}])[0] == 400
    assert raw(fake, "PUT", url, [good, good])[0] == 400
    assert raw(fake, "PUT", url, [{**good, "name": f"c{i}"} for i in range(101)])[0] == 400
    optional_first = [
        {"name": "a", "description": "x", "type": 3},
        {"name": "b", "description": "x", "type": 3, "required": True},
    ]
    assert raw(fake, "PUT", url, [{**good, "options": optional_first}])[0] == 400


def test_lockdown_lasts_at_most_twenty_four_hours(fake):
    give_bot(fake, "manage_guild")
    from datetime import UTC, datetime, timedelta

    far = (datetime.now(UTC) + timedelta(hours=30)).isoformat()
    assert raw(fake, "PUT", f"/guilds/{gid(fake)}/incident-actions", {"invites_disabled_until": far})[0] == 400


def test_messages_are_limited_to_2000_characters_and_an_audit_reason_to_512(fake):
    give_bot(fake, "manage_channels")
    channel = fake.add_channel("c", TEXT)
    status, _ = raw(fake, "POST", f"/channels/{channel['id']}/messages", {"content": "x" * 2001})
    assert status == 400
    status, _ = raw(fake, "PATCH", f"/guilds/{gid(fake)}/channels", [], headers={"X-Audit-Log-Reason": "r" * 513})
    assert status == 400


def test_the_fake_records_every_change_in_its_audit_log_with_the_reason(fake):
    give_bot(fake, "manage_channels")
    raw(
        fake,
        "POST",
        f"/guilds/{gid(fake)}/channels",
        {"name": "c", "type": 0},
        headers={"X-Audit-Log-Reason": "Because%20reasons"},
    )
    assert fake.audit[-1]["reason"] == "Because reasons"
    assert json.dumps(fake.audit[-1])


def test_the_api_base_is_refused_unless_it_is_local():
    from serverkit.http import resolve_base

    assert resolve_base(None).startswith("https://discord.com/api/")
    assert resolve_base("http://127.0.0.1:9/api/v10") == "http://127.0.0.1:9/api/v10"
    assert resolve_base("http://localhost:9") == "http://localhost:9"
    for bad in ("https://discord.com/api/v10", "http://example.org", "http://127.0.0.1.evil.example"):
        with pytest.raises(ValueError):
            resolve_base(bad)
