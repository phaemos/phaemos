"""Pointers at private channels, steps that carry on, the new channels and the pinned Read first posts."""

from __future__ import annotations

import re

import pytest
from conftest import words
from fake_discord import BITS
from helpers import deletes, raw

from serverkit import perms
from serverkit.access import MEMBER, access_in, access_problems


def managed_names(layout):
    return [r.name for r in layout.roles if not r.owner]


def half_applied(make_server, layout):
    """The server as the live run left it: roles and channels made, new roles tied with the bot's own role and
    Discord's private channel still the community updates channel."""
    h = make_server(community=False)
    fake = h.fake
    fake.make_community(wizard_channels=True, wizard_visible_to_bot=False)
    h.owner_roles()
    assert h.apply("--only", "settings,roles,channels").code in (0, 3)
    top = fake.roles[fake.bot_role_id]["position"]
    for name in managed_names(layout):
        fake.role_named(name)["position"] = top
    return h


def drag_below_the_bot(h, layout):
    """What the owner does by hand: the roles the script manages go under the bot's role."""
    fake = h.fake
    top = fake.roles[fake.bot_role_id]["position"]
    for place, name in enumerate(managed_names(layout), 1):
        fake.role_named(name)["position"] = top - place


# ---- fault 1: the pointer at a channel the bot cannot see -----------------------------------------------------------


def test_a_pointer_at_a_private_channel_is_an_owner_step_and_not_an_error(make_server, layout):
    h = half_applied(make_server, layout)
    fake = h.fake
    hidden = fake.guild["public_updates_channel_id"]
    assert hidden not in {c["id"] for c in raw(fake, "GET", f"/guilds/{fake.guild_id}/channels")[1]}
    plan = h.plan()
    assert plan.code == 3, plan.out
    assert 'set "Community updates channel" to the #moderator-only under Staff' in plan.out
    result = h.apply()
    assert result.code == 3, result.out + result.err
    assert "error" not in [w for w, _ in words(result.out)]
    assert not [r for r in fake.requests if r[0] == "PATCH" and r[1] == f"/guilds/{fake.guild_id}" and r[2] == 403]
    # the owner makes the change by hand and the next run is clean
    ours = next(c["id"] for c in fake.channels.values() if c["name"] == "moderator-only" and c["id"] != hidden)
    fake.guild["public_updates_channel_id"] = ours
    fake.guild["safety_alerts_channel_id"] = ours
    drag_below_the_bot(h, layout)
    assert h.apply().code == 0
    assert h.plan().code == 0


def test_the_fake_refuses_the_pointer_patch_while_the_current_channel_is_hidden(make_server, layout):
    h = half_applied(make_server, layout)
    fake = h.fake
    ours = next(c["id"] for c in fake.channels.values() if c["name"] == "moderator-only" and c["type"] == 0)
    status, _ = raw(fake, "PATCH", f"/guilds/{fake.guild_id}", {"public_updates_channel_id": ours})
    assert status == 403


# ---- fault 2: role order -----------------------------------------------------------------------------------------


def test_new_roles_are_placed_below_the_bot_in_one_request_and_the_next_preflight_passes(make_server, layout):
    h = make_server()
    fake = h.fake
    result = h.apply()
    assert result.code == 0, result.out + result.err
    placements = [a for a in fake.audit if a["reason"].endswith("place the new roles below the bot's role")]
    assert len(placements) == 1, "one request"
    top = fake.roles[fake.bot_role_id]["position"]
    positions = [fake.role_named(n)["position"] for n in managed_names(layout)]
    assert all(p < top for p in positions) and positions == sorted(positions, reverse=True)
    plan = h.plan()
    assert plan.code == 0 and "error" not in [w for w, _ in words(plan.out)]


def test_a_tie_with_the_bots_role_is_an_owner_step_and_never_an_error(make_server, layout):
    h = half_applied(make_server, layout)
    plan = h.plan()
    assert "tie with the bot's role" in plan.out
    assert "does not say which way" in plan.out
    assert any(w == "blocked" and "role order" in t for w, t in words(plan.out))
    assert "drag" in plan.out and "below the bot's role" in plan.out
    result = h.apply()
    assert result.code == 3 and "error" not in [w for w, _ in words(result.out)], result.out
    fake = h.fake
    top = fake.roles[fake.bot_role_id]["position"]
    assert all(fake.role_named(n)["position"] == top for n in managed_names(layout)), "the bot moved nothing"
    # the owner drags them and the next run is clean
    hidden = fake.guild["public_updates_channel_id"]
    fake.guild["public_updates_channel_id"] = next(
        c["id"] for c in fake.channels.values() if c["name"] == "moderator-only" and c["id"] != hidden
    )
    fake.guild["safety_alerts_channel_id"] = fake.guild["public_updates_channel_id"]
    drag_below_the_bot(h, layout)
    final = h.apply()
    assert final.code == 0, final.out
    assert h.plan().code == 0


def test_if_discord_refuses_to_place_new_roles_it_is_an_owner_step_and_the_run_carries_on(make_server, layout):
    h = make_server()
    h.fake.ties_block = True
    h.fake.new_roles_tie = True
    result = h.apply()
    assert "error" not in [w for w, _ in words(result.out)], result.out
    assert h.fake.commands, "a step that reads no role still ran"


# ---- steps that carry on --------------------------------------------------------------------------------------------


def test_an_independent_step_carries_on_after_another_one_fails(server):
    server.fake.fail_next(r"/auto-moderation/rules$", "500", times=999, method="POST")
    result = server.apply()
    assert result.code == 1
    fake = server.fake
    # settings, commands, messages, pins and webhooks read nothing from auto moderation, so they were done
    assert fake.commands and fake.webhooks and fake.guild["verification_level"] == 2
    assert fake.messages.get(fake.by_name("rules")["id"])
    # onboarding reads roles and channels only, so it was done too
    assert fake.onboarding["prompts"]


def test_a_step_that_needs_a_failed_one_is_skipped_and_named(server):
    server.fake.fail_next(r"/guilds/\d+/channels$", "500", times=999, method="POST")
    result = server.apply()
    assert result.code == 1
    skipped = [t for w, t in words(result.out) if w == "skipped"]
    assert any("needs channels" in t for t in skipped), result.out
    assert not server.fake.messages and not server.fake.webhooks
    # roles and commands do not read channels, so they were done
    assert server.fake.commands
    server.fake.faults.clear()
    assert server.apply().code == 0
    assert server.plan().code == 0


def test_three_refusals_stop_everything(make_server, layout):
    h = make_server()
    fake = h.fake
    seen = {"n": 0}

    def strip(f):
        seen["n"] += 1
        if seen["n"] == 3:
            f.roles[f.bot_role_id]["permissions"] = str(
                int(f.roles[f.bot_role_id]["permissions"]) & ~BITS["manage_channels"] & ~BITS["manage_guild"]
            )

    fake.after_write = strip
    result = h.apply()
    assert result.code == 1
    assert len([r for r in fake.requests if r[2] == 403]) <= 3


# ---- the new channels --------------------------------------------------------------------------------------------------


def need(layout, name):
    channel = layout.channel(name)
    if channel is None:
        pytest.skip(f"this project has no {name}")
    return channel


def test_members_cannot_open_private_threads_and_moderators_can_only_in_private_help(layout):
    need(layout, "private-help")
    for channel in layout.active_channels:
        member = access_in(layout, MEMBER, [], channel)
        assert not member.has("create_private_threads"), channel.name
        holds = layout.role("Moderator").permissions & perms.BIT["create_private_threads"]
        assert holds == 0
        # the owner sets the role itself, so the channel row is what grants it
        row = next((o for o in channel.overwrites if o.target == "Moderator"), None)
        granted = bool(row and row.allow & perms.BIT["create_private_threads"])
        assert granted is (channel.name == "private-help"), channel.name
    private = access_in(layout, MEMBER, [], layout.channel("private-help"))
    assert private.reads and not private.posts and private.replies_in_threads


def test_the_staff_channels_are_hidden_and_the_docs_channel_is_read_only(layout, server):
    for name in ("tickets", "staff-voice", "ci-alerts"):
        channel = need(layout, name)
        assert channel.staff
        assert not access_in(layout, MEMBER, [], channel).visible
        assert access_in(layout, "Moderator", ["Moderator"], channel).visible
    docs = need(layout, "docs")
    member = access_in(layout, MEMBER, [], docs)
    assert member.reads and not member.posts and not member.reacts
    assert access_problems(layout) == []
    assert layout.channel("staff-voice").type == "voice" and layout.channel("tickets").type == "forum"
    assert not layout.channel("tickets").forum["require_tag"]


def test_the_new_channels_are_built_and_the_second_plan_is_empty(server, layout):
    assert server.apply().code == 0
    fake = server.fake
    for name in ("private-help", "docs", "tickets", "staff-voice", "ci-alerts", "ideas", "research"):
        need(layout, name)
        assert fake.by_name(name)
    assert fake.by_name("staff-voice")["type"] == 2 and fake.by_name("tickets")["type"] == 15
    assert fake.by_name("docs")["parent_id"] == fake.by_name("Resources", 4)["id"]
    assert server.plan().code == 0


def test_every_forum_tag_is_words_and_no_name_holds_an_emoji(layout):
    for channel in layout.channels:
        for tag in (channel.forum or {}).get("tags", []):
            assert re.search(r"[A-Za-z]", tag["name"]) and tag["name"].isascii(), tag
            assert tag.get("emoji") is None
        assert channel.name.isascii() and re.search(r"[A-Za-z]", channel.name)


def test_the_project_layouts_hold_nothing_back_and_every_channel_is_created_on_the_first_apply(layout, server):
    assert all(c.enabled and not c.threshold for c in layout.channels)
    assert all(c.enabled for c in layout.categories)
    assert len(layout.active_channels) == len(layout.channels)
    for name in ("ideas", "research"):
        assert layout.channel_active(layout.channel(name)) and layout.channel(name).type == "forum"
    assert server.apply().code == 0
    made = {c["name"] for c in server.fake.channels.values()}
    assert {c.name for c in layout.channels} <= made


def test_a_layout_can_still_hold_a_channel_back_and_the_plan_says_so(make_server, tmp_path):
    from helpers import holding_back, layout_data, write_layout

    data = layout_data()
    holding_back(data, "private-help", "50 members")
    path = write_layout(tmp_path, data)
    h = make_server()
    assert h.apply(layout=path).code == 0
    assert "private-help" not in {c["name"] for c in h.fake.channels.values()}
    assert "deferred" in h.plan(layout=path).out or "50 members" in h.plan(layout=path).out


# ---- Read first posts -------------------------------------------------------------------------------------------------


def forum_posts(fake, forum_name):
    forum = fake.by_name(forum_name)
    return [t for t in fake.threads.values() if t["parent_id"] == forum["id"]]


def test_each_public_forum_gets_a_pinned_read_first_post_with_the_guidelines_and_the_faq(server, layout):
    assert server.apply().code == 0
    fake = server.fake
    for name in ("help", "hardware", "showcase", "ideas", "research"):
        post = next(t for t in forum_posts(fake, name) if t["name"].startswith("Read first"))
        assert post["flags"] & 2, "pinned"
        assert post["owner_id"] == fake.bot_user_id
        read_first_tag = next(t for t in fake.by_name(name)["available_tags"] if t["name"] == "Read first")
        assert post["applied_tags"] == [read_first_tag["id"]]
        starter = fake.messages[post["id"]][0]
        assert starter["allowed_mentions"] == {"parse": []} and starter["flags"] == 0
        text = starter["embeds"][0]["description"]
        assert layout.channel(name).topic.splitlines()[0] in text
        if name != "showcase":
            assert "We aim to reply within two days. Nobody is on call." in text
        if name in ("ideas", "research"):
            assert "The GitHub discussion is the record" in text and "talking it through" in text
    help_text = fake.messages[next(t for t in forum_posts(fake, "help") if t["name"].startswith("Read first"))["id"]][0]
    faq = layout.commands_content["faq"]
    assert faq
    for entry in faq:
        assert entry["title"] in help_text["embeds"][0]["description"], "built from the one source"


def test_a_read_first_post_is_edited_in_place_and_repinned(server, layout):
    assert server.apply().code == 0
    fake = server.fake
    post = next(t for t in forum_posts(fake, "help") if t["name"].startswith("Read first"))
    fake.messages[post["id"]][0]["embeds"][0]["description"] = "edited by hand"
    post["flags"] = 0
    plan = server.plan()
    assert any("Read first post in #help: text, pin" in t for w, t in words(plan.out) if w == "update")
    count = len(forum_posts(fake, "help"))
    assert server.apply().code == 0
    assert len(forum_posts(fake, "help")) == count and post["id"] in fake.threads, "the same post"
    assert post["flags"] & 2 and "edited by hand" not in fake.messages[post["id"]][0]["embeds"][0]["description"]
    assert server.plan().code == 0
    before = fake.write_count
    assert server.apply().code == 0 and fake.write_count == before


def test_the_fake_keeps_to_the_forum_rules(make_server, layout):
    h = make_server()
    assert h.apply().code == 0
    fake = h.fake
    help_forum = fake.by_name("help")
    url = f"/channels/{help_forum['id']}/threads"
    message = {"embeds": [{"title": "x", "description": "y"}], "flags": 0}
    assert raw(fake, "POST", url, {"name": "no tag", "message": message})[0] == 400, "a tag is required"
    assert raw(fake, "POST", url, {"name": "bad", "message": message, "applied_tags": ["1"]})[0] == 400
    solved = next(t["id"] for t in help_forum["available_tags"] if t["name"] == "Solved")
    assert raw(fake, "POST", url, {"name": "fine", "message": message, "applied_tags": [solved]})[0] == 201
    moderated = next(t["id"] for t in help_forum["available_tags"] if t["name"] == "Read first")
    fake.roles[fake.bot_role_id]["permissions"] = str(
        int(fake.roles[fake.bot_role_id]["permissions"]) & ~BITS["manage_threads"]
    )
    assert raw(fake, "POST", url, {"name": "mod", "message": message, "applied_tags": [moderated]})[0] == 403


def test_check_needs_a_read_first_tag_and_a_forum(tmp_path):
    from conftest import ROOT
    from helpers import errors_of, find, layout_data, write_layout

    data = layout_data()
    forum = next(c for c in data["channels"] if c.get("read_first"))
    forum["forum"]["tags"] = [t for t in forum["forum"]["tags"] if t["name"] != "Read first"]
    assert any('needs a tag named "Read first"' in p for p in errors_of(write_layout(tmp_path, data), ROOT))
    data = layout_data()
    find(data["channels"], "general")["read_first"] = forum["read_first"]
    assert any("read_first is for a forum" in p for p in errors_of(write_layout(tmp_path, data, "b.toml"), ROOT))


def test_nothing_in_the_new_texts_pings_or_holds_an_id(server, layout):
    assert server.apply().code == 0
    for messages in server.fake.messages.values():
        for message in messages:
            assert message.get("allowed_mentions", {"parse": []}) == {"parse": []}
    assert deletes(server.fake) == []


# ---- tickets: the secrets the worker needs ----------------------------------------------------------------------


def test_sync_secrets_stores_the_ticket_tag_ids_on_standard_input_only(server, layout):
    kinds = (layout.commands_content or {}).get("ticket_kinds")
    if not kinds or layout.channel("tickets") is None:
        pytest.skip("this project has no ticket forum")
    assert server.apply().code == 0
    result = server.run("sync-secrets")
    assert result.code == 0, result.out + result.err
    fake = server.fake
    jobs = {tuple(c): v for c, v in result.stored}
    tickets = [(c, v) for c, v in jobs.items() if "TICKETS_WEBHOOK_URL" in c]
    assert len(tickets) == 1 and "wrangler" in " ".join(tickets[0][0])
    assert tickets[0][1] in {h["url"] for h in fake.webhooks.values()}
    tags = [(c, v) for c, v in jobs.items() if "TICKET_TAG_IDS" in c]
    assert len(tags) == 1
    command, value = tags[0]
    forum_tags = {t["name"]: t["id"] for t in fake.by_name("tickets")["available_tags"]}
    expected = ",".join(f"{k['key']}:{forum_tags[k['title']]}" for k in kinds)
    assert value == expected
    for tag_id in forum_tags.values():
        assert not any(tag_id in part for part in command)
        assert tag_id not in result.out and tag_id not in result.err
    assert f"TICKET_TAG_IDS (cloudflare): {len(kinds)} tags" in result.out


def test_every_ticket_kind_is_a_tag_of_the_tickets_forum(layout):
    kinds = (layout.commands_content or {}).get("ticket_kinds")
    if not kinds:
        pytest.skip("this project has no ticket kinds")
    tags = {t["name"] for t in layout.channel("tickets").forum["tags"]}
    assert {k["title"] for k in kinds} <= tags


# ---- retired commands -------------------------------------------------------------------------------------------


def test_a_retired_command_is_removed_and_a_command_someone_else_made_is_not(server, layout):
    retired = layout.commands.get("retired", [])
    assert retired, "the layout lists the commands it replaced"
    assert server.apply().code == 0
    fake = server.fake
    fake.commands.append({"id": "9001", "name": retired[0], "description": "the old one", "type": 1})
    fake.commands.append({"id": "9002", "name": "someones-own", "description": "made by a person", "type": 1})
    plan = server.plan()
    assert any(w == "delete" and f"/{retired[0]}" in t for w, t in words(plan.out))
    assert any(w == "unmanaged" and "someones-own" in t for w, t in words(plan.out))
    assert server.apply().code == 0
    names = {c["name"] for c in fake.commands}
    assert retired[0] not in names and "someones-own" in names
    assert server.plan().code == 0


def test_the_ticket_and_issue_commands_are_registered_with_their_options(server, layout):
    assert server.apply().code == 0
    by_name = {c["name"]: c for c in server.fake.commands}
    assert [o["name"] for o in by_name["issue"]["options"]] == ["show", "new"]
    ticket = by_name["ticket"]
    assert [c["value"] for c in ticket["options"][0]["choices"]] == [
        k["key"] for k in layout.commands_content["ticket_kinds"]
    ]


def test_ideas_and_research_are_open_forums_with_tags_in_words(layout):
    for name in ("ideas", "research"):
        channel = layout.channel(name)
        assert channel.category == "Community" and channel.forum["require_tag"]
        member = access_in(layout, MEMBER, [], channel)
        assert member.reads and member.posts, "visible and postable from day one"
        tags = [t["name"] for t in channel.forum["tags"]]
        assert "Read first" in tags and len(tags) <= 20 and all(len(t) <= 20 for t in tags)
    # five channels members can post in were enough for onboarding and there are more now
    assert layout.onboarding["default_channels"].count("ideas") == 0
