"""Managed posts, roles, onboarding, the system channel, bot commands, error output and secret patterns."""

from __future__ import annotations

import shutil

MEMBER = str(7 * 10**17 + 1)  # made at run time: no file holds an identifier


def test_managed_messages_are_found_after_250_member_messages(server):
    assert server.apply().code == 0
    fake = server.fake
    for n in range(250):
        fake.add_message("contributing", f"member line {n}", author_id=MEMBER)
        fake.add_message("rules", f"member line {n}", author_id=MEMBER)
    plan = server.plan()
    assert plan.code == 0, plan.out
    assert "create message" not in plan.out and "create pin" not in plan.out
    assert server.apply().code == 0
    roadmap = [m for m in fake.messages[fake.by_name("contributing")["id"]] if m["author"]["id"] == fake.bot_user_id]
    assert len(roadmap) == len([m for m in roadmap if m.get("pinned")]) == 1


def readfirst_posts(fake, forum="help"):
    parent = fake.by_name(forum)["id"]
    return [t for t in fake.threads.values() if t["parent_id"] == parent and t["owner_id"] == fake.bot_user_id]


def test_an_archived_read_first_post_is_reopened_not_duplicated(server):
    assert server.apply().code == 0
    fake = server.fake
    [post] = readfirst_posts(fake)
    post["thread_metadata"]["archived"] = True
    post["flags"] &= ~2  # archiving unsets the pin
    plan = server.plan()
    assert "reopen it" in plan.out
    assert server.apply().code == 0
    [post] = readfirst_posts(fake)
    assert not post["thread_metadata"]["archived"] and post["flags"] & 2
    assert server.plan().code == 0


def test_an_edited_first_line_edits_the_post_in_place(server, tmp_path):
    from conftest import ROOT
    from helpers import layout_data, write_layout

    assert server.apply().code == 0
    fake = server.fake
    [before] = readfirst_posts(fake)
    shutil.copytree(ROOT / "texts", tmp_path / "texts")
    (tmp_path / "texts" / "readfirst-help.md").write_text("A new first line\n\nThe rest stays as it was.\n")
    path = write_layout(tmp_path, layout_data())
    assert server.apply(layout=path).code == 0
    [after] = readfirst_posts(fake)
    assert after["id"] == before["id"] and after["name"] == "A new first line" and after["flags"] & 2
    assert server.plan(layout=path).code == 0


def test_a_post_pinned_by_hand_is_an_owner_step_and_never_a_failure(server):
    fake = server.fake
    assert server.apply().code == 0
    [post] = readfirst_posts(fake)
    post["flags"] &= ~2
    hand = fake.add_thread("help", "Pinned by the owner")
    hand.update({"owner_id": str(7 * 10**17 + 2), "flags": 2, "applied_tags": []})
    plan = server.plan()
    assert "one pinned post per forum" in plan.out and "unpin" in plan.out
    applied = server.apply()
    assert "Traceback" not in applied.out and "refused" not in applied.out.lower()
    assert hand["flags"] & 2 and not post["flags"] & 2
    assert len(readfirst_posts(fake)) == 1


def test_a_step_that_was_skipped_also_skips_the_steps_that_need_it():
    from types import SimpleNamespace

    from serverkit.engine import Change
    from serverkit.http import ApiError
    from serverkit.runner import execute

    ran: list[str] = []

    def ok(step):
        return lambda: ran.append(step)

    def boom():
        raise ApiError(500, None, "down", "POST", "/guilds/1/roles")

    changes = [
        Change("roles", "create", "a role", boom),
        Change("channels", "create", "a channel", ok("channels")),
        Change("pointers", "update", "a pointer", ok("pointers")),
        Change("readfirst", "create", "a post", ok("readfirst")),
        Change("messages", "create", "a message", ok("messages")),
        Change("pins", "create", "a pin", ok("pins")),
        Change("webhooks", "create", "a webhook", ok("webhooks")),
        Change("commands", "create", "a command", ok("commands")),
    ]
    result = execute(SimpleNamespace(), SimpleNamespace(changes=changes))
    assert ran == ["commands"], ran
    assert {c.step for c, _ in result.skipped} == {"channels", "pointers", "readfirst", "messages", "pins", "webhooks"}


def test_roles_the_tool_did_not_create_keep_their_places(make_server, layout):
    h = make_server()
    fake = h.fake
    # a hand made role the owner put at the bottom. One the owner put well above the bot's role
    # Discord keeps the places contiguous: five hand made roles at the bottom, the rest shifted up over them
    for role in fake.roles.values():
        if role["id"] != fake.guild_id:
            role["position"] += 5
    below = fake.add_role("Legacy", position=1)
    for n in range(2, 6):
        fake.add_role(f"Hand made {n}", position=n)
    above = fake.add_role("Other bot", position=max(r["position"] for r in fake.roles.values()) + 1)
    others_before = {name: fake.roles[r["id"]]["position"] for name, r in (("below", below), ("above", above))}
    assert h.apply().code == 0
    top = fake.roles[fake.bot_role_id]["position"]
    managed = [r.name for r in layout.roles if not r.owner]
    positions = [fake.role_named(n)["position"] for n in managed]
    # the new roles sit directly under the bot, first in the layout highest and the hand made ones keep their order
    assert positions == sorted(positions, reverse=True) and max(positions) == top - 1
    assert min(positions) > fake.roles[below["id"]]["position"] == 1 == others_before["below"]
    assert fake.roles[above["id"]]["position"] > top
    assert fake.roles[below["id"]]["position"] == 1


def test_onboarding_shows_docs_and_the_new_forums_and_keeps_discords_minimums(layout, server):
    from serverkit import perms
    from serverkit.layout import FORUMS_COUNT_FOR_ONBOARDING

    defaults = layout.onboarding["default_channels"]
    assert "docs" in defaults and len(defaults) >= 7
    postable = 0
    for name in defaults:
        channel = layout.channel(name)
        if channel.type == "forum" and not FORUMS_COUNT_FOR_ONBOARDING:
            continue
        row = next((o for o in channel.overwrites if o.target == "@everyone"), None)
        value = perms.channel_permissions(layout.everyone, (row.allow, row.deny) if row else None, [])
        postable += bool(value & perms.BIT["send_messages"] and value & perms.BIT["view_channel"])
    assert postable >= 5, "at least five default channels that @everyone can send in"
    options = {o["title"]: o for p in layout.onboarding["prompts"] for o in p["options"]}
    assert {"ideas", "research"} <= set(options["I want to contribute"]["channels"])
    if layout.channel("songs"):
        asked = [o for t, o in options.items() if "Piano" in t or "Guitar" in t]
        assert asked and all({"songs", "practice"} <= set(o["channels"]) for o in asked)
    assert server.apply().code == 0
    onboarding = server.fake.onboarding
    assert len(onboarding["default_channel_ids"]) == len(defaults)


def test_sync_secrets_stores_the_forum_tag_ids_for_the_relay(server, layout):
    assert server.apply().code == 0
    result = server.run("sync-secrets")
    assert result.code == 0, result.out + result.err
    fake = server.fake
    for secret, forum in (("DISCORD_TAG_IDEAS", "ideas"), ("DISCORD_TAG_RESEARCH", "research")):
        tag = next(t for t in fake.by_name(forum)["available_tags"] if t["name"] == "From GitHub")
        [(command, value)] = [(c, v) for c, v in result.stored if secret in c]
        assert command[0] == "gh" and value == tag["id"]
        assert tag["id"] not in " ".join(command) and tag["id"] not in result.out


# ---- the welcome channel and join messages ---------------------------------------------------------------------------


def test_the_welcome_channel_is_first_in_start_here_and_nobody_can_write_in_it(layout):
    from serverkit import access
    from serverkit.access import MEMBER, NEW_ARRIVAL

    start = [c.name for c in layout.channels if c.category == "Start here"]
    assert start[0] == "welcome" and start.index("welcome") < start.index("rules")
    assert layout.server["system_channel"] == "welcome"
    grid = access.table(layout)
    for kind in (NEW_ARRIVAL, MEMBER):
        seen = grid[kind]["welcome"]
        assert seen.reads and not seen.posts and not seen.replies_in_threads
        assert seen.reacts or kind == NEW_ARRIVAL, "members react. A new arrival is held to reading"
    for kind, row in grid.items():
        if kind not in ("Maintainer", "Moderator", "bot"):
            assert not row["welcome"].posts, kind


def test_the_flags_show_join_messages_and_sticker_replies_and_hide_boosts_and_tips(layout):
    flags = layout.server["system_channel_flags"]
    assert flags == (1 << 1) | (1 << 2) == 6
    assert not flags & (1 << 0), "SUPPRESS_JOIN_NOTIFICATIONS is not set, so a join is announced"
    assert not flags & (1 << 3), "SUPPRESS_JOIN_NOTIFICATION_REPLIES is not set, so the wave reply stays"
    assert flags & (1 << 1) and flags & (1 << 2)


def test_apply_points_the_system_channel_at_welcome_and_the_second_plan_is_empty(server, layout):
    assert server.apply().code == 0
    fake = server.fake
    assert fake.guild["system_channel_id"] == fake.by_name("welcome")["id"]
    assert fake.guild["system_channel_flags"] == 6
    assert server.plan().code == 0
    before = fake.write_count
    assert server.apply().code == 0 and fake.write_count == before
    # start-here stays read-only for members and keeps its pinned messages
    from serverkit.access import MEMBER, access_in

    assert not access_in(layout, MEMBER, [], layout.channel("start-here")).posts
    start = fake.by_name("start-here")["id"]
    bot = [m for m in fake.messages[start] if m["author"]["id"] == fake.bot_user_id and m.get("type", 0) == 0]
    assert len(bot) == len(layout.channel("start-here").messages) and all(m["pinned"] for m in bot)


def test_the_system_channel_may_not_be_a_channel_members_can_write_in(server, tmp_path):
    from helpers import layout_data, write_layout

    data = layout_data()
    data["server"]["system_channel"] = "general"
    result = server.run("check", layout=write_layout(tmp_path, data))
    assert result.code == 2 and "system channel general" in result.out + result.err


def test_the_system_channel_pointer_works_before_community_is_on(make_server, layout):
    h = make_server(community=False)
    plan = h.plan()
    assert plan.code in (0, 3, 4)
    h.apply("--only", "settings,roles,channels,pointers")
    assert h.fake.guild["system_channel_id"] == h.fake.by_name("welcome")["id"]


# ---- the bot-commands channel --------------------------------------------------------------------------------------


def test_bot_commands_lists_every_member_command_as_a_link_from_the_command_content(server, layout):
    assert server.apply().code == 0
    fake = server.fake
    channel = layout.channel("bot-commands")
    assert channel.category == "Community" and channel.slow_mode == 5 and channel.pin and channel.style == "plain"
    made = fake.by_name("bot-commands")
    assert made["rate_limit_per_user"] == 5
    [message] = [
        m for m in fake.messages[made["id"]] if m["author"]["id"] == fake.bot_user_id and m.get("type", 0) == 0
    ]
    assert message["pinned"] and message["embeds"] == []
    content = layout.commands_content
    shown = [
        c
        for c in content["commands"]
        if not c.get("staff") and c.get("type", "chat_input") != "message" and c.get("help")
    ]
    ids = {c["name"]: c["id"] for c in fake.commands}
    for command in shown:
        assert f"</{command['name']}:{ids[command['name']]}> - {command['help']}" in message["content"], command["name"]
    assert "</mod:" not in message["content"]
    assert len(message["content"]) <= 2000
    assert server.plan().code == 0


def test_a_command_added_to_the_content_appears_in_the_list_without_touching_the_layout(layout):
    from serverkit.layout import commands_block

    content = {
        "commands": [{"name": "newone", "help": "Does a new thing."}, {"name": "hidden", "help": "x", "staff": True}]
    }
    assert commands_block(content) == "- {command:newone} - Does a new thing."
    assert "{command:help}" in commands_block(layout.commands_content)


def test_start_here_and_help_point_at_bot_commands_and_onboarding_keeps_its_minimums(server, layout):
    assert "bot-commands" in layout.onboarding["default_channels"] and len(layout.onboarding["default_channels"]) >= 7
    assert server.apply().code == 0
    fake = server.fake
    where = fake.by_name("bot-commands")["id"]
    text = " ".join(
        m["embeds"][0]["description"] for m in fake.messages[fake.by_name("start-here")["id"]] if m.get("embeds")
    )
    assert f"<#{where}>" in text
    assert layout.commands_content["project"]["commands_channel"] == "bot-commands"


def test_every_text_that_names_the_contact_address_also_links_a_page_that_names_it(layout):
    import re

    address = layout.commands_content["project"]["contact_email"]
    page = layout.commands_content["project"]["contact_page"]
    assert page.startswith("https://github.com/") and page.endswith("/SUPPORT.md")
    for channel in layout.channels:
        for index, text in enumerate(channel.messages, 1):
            if address in text:
                assert re.search(r"<https://github\.com/[^>\s]+/CODE_OF_CONDUCT\.md>", text), (channel.name, index)


# ---- what a refused form says and what check can catch before apply -------------------------------------------------


def test_a_400_prints_every_field_path_code_and_message_with_ids_and_tokens_masked():
    from serverkit.http import error_detail

    token = "A" * 30
    digits = "1" * 18
    payload = {
        "code": 50035,
        "message": "Invalid Form Body",
        "errors": {
            "trigger_metadata": {
                "regex_patterns": {
                    "3": {"_errors": [{"code": "INVALID_REGEX", "message": f"bad near {token} {digits}"}]}
                }
            },
            "name": {"_errors": [{"code": "BASE_TYPE_REQUIRED", "message": "required"}]},
        },
    }
    text = error_detail(payload)
    assert "trigger_metadata.regex_patterns.3: INVALID_REGEX: bad near [masked] [id]" in text
    assert "name: BASE_TYPE_REQUIRED: required" in text
    assert token not in text and digits not in text
    assert error_detail({"message": "x"}) == "" and error_detail("text") == ""


def _pattern_problems(tmp_path, pattern):
    from helpers import errors_of, find, layout_data, write_layout

    data = layout_data()
    find(data["automod"], "Invite links")["patterns"] = [pattern]
    return errors_of(write_layout(tmp_path, data))


def test_check_refuses_the_regex_shapes_discord_cannot_take(tmp_path):
    assert any("Unicode class" in p for p in _pattern_problems(tmp_path, r"x[\w-]{20,}"))
    assert any("lookaround" in p for p in _pattern_problems(tmp_path, r"a(?=b)"))
    assert any("backreference" in p for p in _pattern_problems(tmp_path, r"(a)\1"))
    assert any("1000" in p for p in _pattern_problems(tmp_path, r"a{2000}"))
    assert any("260" in p for p in _pattern_problems(tmp_path, "a" * 261))
    assert _pattern_problems(tmp_path, r"x[A-Za-z0-9_-]{20,}") == []
    assert _pattern_problems(tmp_path, r"\s*https?://") == [], "a Unicode class on its own is small"


def test_check_refuses_more_than_ten_patterns_and_repeated_ones(tmp_path):
    from helpers import errors_of, find, layout_data, write_layout

    data = layout_data()
    find(data["automod"], "Invite links")["patterns"] = [f"a{i}" for i in range(11)]
    assert any("at most 10" in p for p in errors_of(write_layout(tmp_path, data)))
    find(data["automod"], "Invite links")["patterns"] = ["abc", "abc"]
    assert any("listed twice" in p for p in errors_of(write_layout(tmp_path, data)))


def test_the_real_secret_patterns_are_plain_ascii_and_within_every_limit(layout):
    from serverkit.layout import regex_problems

    text = (layout.base_dir / "texts" / "secret-patterns.txt").read_text()
    patterns = [line for line in text.splitlines() if line.strip()]
    assert 1 <= len(patterns) <= 10
    for pattern in patterns:
        assert len(pattern) <= 260 and pattern.isascii() and regex_problems(pattern) == [], pattern


def _onboarding_errors(tmp_path, change):
    from helpers import errors_of, layout_data, write_layout

    data = layout_data()
    change(data)
    return errors_of(write_layout(tmp_path, data))


def test_check_refuses_onboarding_defaults_and_options_discord_would_refuse(tmp_path):
    voice = next(c["name"] for c in layout_data_channels() if c["type"] == "voice" and c.get("category") != "Staff")
    assert any(
        "Only text, announcement and forum" in p
        for p in _onboarding_errors(tmp_path, lambda d: d["onboarding"]["default_channels"].append(voice))
    )
    assert any(
        "is private" in p
        for p in _onboarding_errors(tmp_path, lambda d: d["onboarding"]["default_channels"].append("mod-log"))
    )
    assert any(
        "listed twice" in p
        for p in _onboarding_errors(tmp_path, lambda d: d["onboarding"]["default_channels"].append("rules"))
    )
    assert any(
        "must be text, announcement or forum" in p
        for p in _onboarding_errors(
            tmp_path, lambda d: d["onboarding"]["prompts"][0]["options"][0]["channels"].append(voice)
        )
    )
    assert any(
        "private, so nobody can be added" in p
        for p in _onboarding_errors(
            tmp_path, lambda d: d["onboarding"]["prompts"][0]["options"][0]["channels"].append("mod-log")
        )
    )
    # forums do not count towards the five channels everyone can write in
    forums = [c["name"] for c in layout_data_channels() if c["type"] == "forum"]
    assert any(
        "at least 5" in p
        for p in _onboarding_errors(
            tmp_path,
            lambda d: d["onboarding"].update(
                default_channels=["rules", "start-here", "docs", "announcements", "releases", "general", *forums]
            ),
        )
    )


def layout_data_channels():
    from helpers import layout_data

    return layout_data()["channels"]


def test_the_real_defaults_keep_at_least_five_plain_channels_everyone_can_write_in(layout):
    from serverkit import perms

    plain = 0
    for name in layout.onboarding["default_channels"]:
        channel = layout.channel(name)
        row = next((o for o in channel.overwrites if o.target == "@everyone"), None)
        value = perms.channel_permissions(layout.everyone, (row.allow, row.deny) if row else None, [])
        plain += channel.type != "forum" and bool(
            value & perms.BIT["send_messages"] and value & perms.BIT["view_channel"]
        )
    assert plain >= 5 and len(layout.onboarding["default_channels"]) >= 7


# ---- images as Discord returns them -----------------------------------------------------------------------------------


def _returned(kind_hashes, attachments=False, description=None):
    """A message as the API is believed to return it: the embed holds each image as a signed CDN address and the
    attachment list may be empty."""
    ids = "/".join(str(11 * 10**17 + n) for n in (1, 2))
    base = f"https://cdn.discordapp.com/attachments/{ids}/"
    tail = "?ex=66f00000&is=66ef0000&hm=" + "ab" * 32 + "&"
    names = {k: f"{k}-{h}.png" for k, h in kind_hashes.items()}
    embed = {"title": "t", "description": "d", "color": 1}
    if "logo" in names:
        embed["thumbnail"] = {
            "url": base + names["logo"] + tail,
            "proxy_url": "https://media.discordapp.net/x",
            "width": 512,
        }
    if "banner" in names:
        embed["image"] = {"url": base + names["banner"] + tail, "width": 1280, "height": 640}
    rows = []
    if attachments:
        rows = [
            {"id": str(i), "filename": n, **({"description": description} if description else {})}
            for i, n in enumerate(names.values(), 1)
        ]
    return {"content": "", "embeds": [embed], "flags": 0, "attachments": rows}


def _wanted(kind_hashes, alt=""):
    files = [(f"{k}-{h}.png", b"") for k, h in kind_hashes.items()]
    return {
        "content": "",
        "flags": 0,
        "embeds": [{"title": "t", "description": "d", "color": 1}],
        "files": files,
        "alts": {name: alt for name, _ in files},
    }


def test_images_are_read_from_the_embed_address_whether_or_not_the_attachment_list_holds_them():
    from serverkit.engine import message_differences

    both = {"banner": "1a2b3c4d", "logo": "0f0e0d0c"}
    for attachments in (False, True):
        assert message_differences(_wanted(both), _returned(both, attachments)) == []
    # a changed picture is still seen, by the hash in its name and named for what it is
    assert message_differences(_wanted(both), _returned({"banner": "ffffffff", "logo": "0f0e0d0c"})) == ["banner image"]
    assert message_differences(_wanted(both), _returned({"logo": "0f0e0d0c"})) == ["banner image"]
    assert message_differences(_wanted(both), _returned({"banner": "1a2b3c4d", "logo": "11111111"})) == ["logo image"]
    # alt text is compared only where Discord returns it
    assert message_differences(_wanted(both, "alt"), _returned(both, False)) == []
    assert message_differences(_wanted(both, "alt"), _returned(both, True, "alt")) == []
    assert message_differences(_wanted(both, "alt"), _returned(both, True, "other")) == ["alt text"]


def test_after_apply_the_plan_shows_nothing_when_discord_holds_the_images_only_in_the_embed(make_server, layout):
    h = make_server(discord_like_embed_files=True)
    assert h.apply().code == 0
    fake = h.fake
    start = [m for m in fake.messages[fake.by_name("start-here")["id"]] if m["author"]["id"] == fake.bot_user_id]
    assert start and all(m["attachments"] == [] for m in start)
    assert all("?ex=" in m["embeds"][0]["thumbnail"]["url"] for m in start)
    plan = h.plan()
    assert plan.code == 0 and "image" not in plan.out, plan.out
    before = fake.write_count
    assert h.apply().code == 0 and fake.write_count == before, "nothing is uploaded again"
    assert h.plan().code == 0
