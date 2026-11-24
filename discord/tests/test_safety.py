"""Lockout, leak and least privilege: who can see and do what in every channel."""

from __future__ import annotations

import pytest
from conftest import layout_path
from fake_discord import ALL, BITS
from helpers import find, layout_data, write_layout

from serverkit import access, perms
from serverkit.access import BOT, MEMBER, NEW_ARRIVAL, Access
from serverkit.layout import load

PUBLIC_READ_ONLY = ("rules", "start-here")
NEWS = ("announcements", "releases")
CHAT = ("general", "contributing")
FORUMS = ("help", "hardware", "showcase")
FEED = ("github-feed",)
STAFF = ("moderator-only", "mod-log")


@pytest.fixture
def grid(layout):
    return access.table(layout)


def present(layout, names):
    return [n for n in names if layout.channel(n) and layout.channel_active(layout.channel(n))]


# ---- the visibility table of the specification, cell by cell ----------------------------------


def test_the_public_read_only_channels(layout, grid):
    for name in present(layout, PUBLIC_READ_ONLY):
        for kind in (NEW_ARRIVAL, MEMBER, "Contributor", "Moderator", "Maintainer"):
            cell = grid[kind][name]
            assert cell.reads and not cell.posts and not cell.reacts, (kind, name)
        assert grid[BOT][name].reads and grid[BOT][name].posts


def test_news_channels_can_be_read_and_reacted_to_and_only_maintainers_post_in_announcements(layout, grid):
    for name in present(layout, NEWS):
        assert grid[NEW_ARRIVAL][name].reads and not grid[NEW_ARRIVAL][name].reacts
        for kind in (MEMBER, "Contributor", "Moderator", "Maintainer"):
            assert (
                grid[kind][name].reads
                and grid[kind][name].reacts
                and not grid[kind][name].posts
                or (name == "announcements" and kind == "Maintainer")
            ), (kind, name)
        assert grid[BOT][name].posts
    assert grid["Maintainer"]["announcements"].posts
    for kind in (MEMBER, "Contributor", "Moderator"):
        assert not grid[kind]["announcements"].posts


def test_chat_and_forum_channels_are_open_and_staff_have_their_tools(layout, grid):
    for name in present(layout, CHAT + FORUMS):
        assert grid[NEW_ARRIVAL][name].reads and not grid[NEW_ARRIVAL][name].posts
        for kind in (MEMBER, "Contributor"):
            cell = grid[kind][name]
            assert cell.reads and cell.posts and cell.reacts
            assert not cell.deletes and not cell.pins and not cell.manages_threads
        mod = grid["Moderator"][name]
        assert mod.posts and mod.deletes and mod.pins and not mod.manages_threads
        boss = grid["Maintainer"][name]
        assert boss.posts and boss.deletes and boss.pins and boss.manages_threads
        assert grid[BOT][name].reads and grid[BOT][name].posts


def test_the_github_feed_is_read_only_for_people_and_deletable_by_staff(layout, grid):
    for name in present(layout, FEED):
        for kind in (MEMBER, "Contributor", "Moderator", "Maintainer"):
            assert grid[kind][name].reads and grid[kind][name].reacts and not grid[kind][name].posts
        assert grid["Moderator"][name].deletes and grid["Maintainer"][name].deletes
        assert grid[BOT][name].reads and not grid[BOT][name].posts


def test_staff_channels_are_hidden_from_everyone_else(layout, grid):
    for name in present(layout, STAFF):
        for kind in (
            NEW_ARRIVAL,
            MEMBER,
            "Contributor",
            *[r.name for r in layout.roles if r.name not in ("Moderator", "Maintainer")],
        ):
            assert grid[kind][name].value == 0, (kind, name)
        for kind in ("Moderator", "Maintainer"):
            assert grid[kind][name].reads
        assert grid[BOT][name].reads and grid[BOT][name].posts


def test_the_moderation_log_is_read_only_for_staff_and_a_moderator_cannot_delete_in_it(layout, grid):
    name = "mod-log"
    for kind in ("Moderator", "Maintainer"):
        cell = grid[kind][name]
        assert not cell.posts and cell.replies_in_threads
    assert not grid["Moderator"][name].deletes
    assert grid["Maintainer"][name].deletes
    assert grid["Moderator"]["moderator-only"].posts and grid["Maintainer"]["moderator-only"].posts
    assert grid[BOT][name].posts


def test_the_layout_passes_its_own_access_check(layout):
    assert access.access_problems(layout) == []


# ---- the same table taken from the fake after a real build -----------------------------------


def test_the_fakes_arithmetic_gives_the_same_table_after_a_build(server, layout, grid):
    assert server.apply().code == 0
    fake = server.fake
    roles = {r.name: [r.name] for r in layout.roles}
    for channel in layout.active_channels:
        for kind, names in (*roles.items(), (MEMBER, []), (NEW_ARRIVAL, [])):
            mine = grid[kind][channel.name]
            theirs = Access(fake.perms_for_roles(names, channel.name))
            if kind == NEW_ARRIVAL:
                theirs = Access(theirs.value & access.ARRIVAL_MASK)
            assert (
                mine.visible,
                mine.reads,
                mine.posts,
                mine.reacts,
                mine.deletes,
                mine.pins,
                mine.manages_threads,
            ) == (
                theirs.visible,
                theirs.reads,
                theirs.posts,
                theirs.reacts,
                theirs.deletes,
                theirs.pins,
                theirs.manages_threads,
            ), (kind, channel.name)
        assert Access(fake.bot_in(fake.by_name(channel.name))).posts == grid[BOT][channel.name].posts


# ---- lockout -----------------------------------------------------------------------------------


def test_the_owner_holds_everything_in_every_channel(server):
    assert server.apply().code == 0
    fake = server.fake
    assert all(fake.in_channel(c, [], fake.owner_id) == ALL for c in fake.channels.values())


def test_after_every_single_write_the_bot_can_still_view_and_manage_every_channel(server, layout):
    fake = server.fake
    seen: list[str] = []

    def invariant(f):
        for channel in f.channels.values():
            held = f.bot_in(channel)
            if channel["type"] == 4:
                continue
            for name in ("view_channel", "manage_channels"):
                assert held & BITS[name], (name, channel["name"])
        seen.append("ok")

    fake.after_write = invariant
    assert server.apply().code == 0
    assert len(seen) > 50


def test_the_bot_keeps_its_row_in_the_same_request_as_the_everyone_deny(server, layout):
    fake = server.fake
    assert server.apply().code == 0
    created = [r for r in fake.requests if r[0] == "POST" and r[1].endswith("/channels")]
    assert created
    # each hidden channel exists with both rows, so there was never a moment with the deny alone
    staff = fake.by_name("mod-log")
    rows = {o["id"]: o for o in staff["permission_overwrites"]}
    assert int(rows[fake.guild_id]["deny"]) & BITS["view_channel"]
    assert int(rows[fake.bot_role_id]["allow"]) & BITS["view_channel"]


def test_a_write_that_would_lock_the_bot_out_is_stopped_before_it_is_sent(server, layout):
    assert server.apply().code == 0
    fake = server.fake
    # someone adds a row for the bot's own account that takes away what it needs
    channel = fake.by_name("general")
    channel["permission_overwrites"].append(
        {"id": fake.bot_user_id, "type": 1, "allow": "0", "deny": str(BITS["manage_channels"])}
    )
    channel["topic"] = "changed so that a write is planned"
    # the bot could no longer edit it anyway: the script must refuse before sending
    count = len([r for r in fake.requests if r[0] == "PATCH" and channel["id"] in r[1]])
    result = server.apply()
    assert result.code == 1
    assert "left without manage_channels" in result.out
    assert len([r for r in fake.requests if r[0] == "PATCH" and channel["id"] in r[1]]) == count


def test_the_bots_own_role_is_never_changed_or_reordered(server, layout):
    assert server.apply().code == 0
    fake = server.fake
    assert not [a for a in fake.audit if fake.bot_role_id in a["route"]]
    assert int(fake.roles[fake.bot_role_id]["permissions"]) == layout.bot_permissions()


# ---- leaks and a layout that would cause one ------------------------------------------------------


def mutated(tmp_path, change):
    data = layout_data()
    change(data)
    return load(write_layout(tmp_path, data), base_dir=layout_path().parent.parent)


def test_a_layout_that_shows_a_staff_channel_fails_the_check(tmp_path):
    def open_staff(data):
        category = find(data["categories"], "Staff")
        category["overwrites"] = [o for o in category["overwrites"] if o["target"] != "@everyone"]

    problems = access.access_problems(mutated(tmp_path, open_staff))
    assert any("visible to member" in p for p in problems), problems


def test_a_layout_that_lets_a_recognition_role_see_staff_fails_the_check(tmp_path):
    def leak(data):
        channel = find(data["channels"], "mod-log")
        channel["overwrites"].append({"target": "Contributor", "allow": ["view_channel"]})

    problems = access.access_problems(mutated(tmp_path, leak))
    assert any("visible to Contributor" in p for p in problems), problems


def test_a_layout_that_hides_the_rules_fails_the_check(tmp_path):
    def hide(data):
        rules = find(data["channels"], data["server"]["rules_channel"])
        rules["overwrites"] = [{"target": "@everyone", "deny": ["view_channel"]}]

    def hide_and_drop_from_onboarding(data):
        hide(data)
        data["onboarding"]["default_channels"].remove(data["server"]["rules_channel"])

    problems = access.access_problems(mutated(tmp_path, hide_and_drop_from_onboarding))
    assert any("cannot read the rules channel" in p for p in problems), problems


def test_a_layout_that_locks_staff_out_fails_the_check(tmp_path):
    def lock(data):
        category = find(data["categories"], "Staff")
        category["overwrites"] = [o for o in category["overwrites"] if o["target"] != "Moderator"]

    problems = access.access_problems(mutated(tmp_path, lock))
    assert any("lock staff out" in p and "Moderator" in p for p in problems), problems


def without_bot_row(layout, category_name):
    """The layout as it would be if the bot's row were missing from a category and its channels.

    The loader gives the bot back whatever a category denies, so the row is taken out after loading.
    """
    category = layout.category(category_name)
    category.overwrites = [o for o in category.overwrites if o.target != "@bot"]
    for channel in layout.channels:
        if channel.category == category_name:
            channel.overwrites = [o for o in channel.overwrites if o.target != "@bot"]
    return layout


def test_a_layout_that_hides_a_channel_from_the_bot_fails_the_check(layout):
    problems = access.access_problems(without_bot_row(layout, "Staff"))
    assert any("the bot cannot see" in p for p in problems), problems


def test_a_layout_that_stops_the_bot_posting_in_the_rules_channel_fails_the_check(layout):
    problems = access.access_problems(without_bot_row(layout, "Start here"))
    assert any("cannot post in" in p for p in problems), problems


def test_plan_and_apply_refuse_a_leaky_layout(server, tmp_path):
    data = layout_data()
    category = find(data["categories"], "Staff")
    category["overwrites"] = [o for o in category["overwrites"] if o["target"] != "@everyone"]
    path = write_layout(tmp_path, data)
    assert server.plan(layout=path).code == 2
    assert server.apply(layout=path).code == 2
    assert server.run("check", layout=path).code == 2
    assert not server.fake.channels


# ---- least privilege -------------------------------------------------------------------------------


def test_no_role_and_no_overwrite_carries_a_structural_permission(layout):
    for role in layout.roles:
        assert not role.permissions & perms.STRUCTURAL_MASK, role.name
    assert not layout.everyone & perms.STRUCTURAL_MASK
    owners = {r.name for r in layout.roles if r.owner}
    for channel in layout.channels:
        for row in channel.overwrites:
            held = row.allow & perms.STRUCTURAL_MASK
            if channel.type == "stage" and row.target in owners:
                # a stage moderator needs Manage Channels on the stage itself and on nothing else
                held &= ~perms.BIT["manage_channels"]
            assert not held, (channel.name, row.target)
    for category in layout.categories:
        for row in category.overwrites:
            assert not row.allow & perms.STRUCTURAL_MASK


def test_a_moderator_cannot_kick_ban_or_manage_threads_and_nobody_can_mention_everyone_but_maintainers(layout):
    moderator = layout.role("Moderator").permissions
    for name in (
        "kick_members",
        "ban_members",
        "manage_threads",
        "view_audit_log",
        "mention_everyone",
        "create_instant_invite",
    ):
        assert not moderator & perms.BIT[name], name
    assert moderator == layout.sets["moderator"]
    assert not layout.everyone & perms.BIT["mention_everyone"]
    assert not layout.everyone & perms.BIT["create_instant_invite"]
    assert not layout.everyone & perms.BIT["create_private_threads"]
    maintainer = layout.role("Maintainer").permissions
    assert maintainer & perms.BIT["mention_everyone"] and maintainer & perms.BIT["manage_threads"]


def test_the_recognition_and_interest_roles_hold_nothing_and_no_one_is_mentionable(layout):
    for role in layout.roles:
        if role.name not in ("Maintainer", "Moderator"):
            assert role.permissions == 0, role.name
        assert role.mentionable is False
        assert role.colour == 0


def test_the_bot_role_never_holds_administrator_in_the_built_server(server):
    assert server.apply().code == 0
    fake = server.fake
    assert not int(fake.roles[fake.bot_role_id]["permissions"]) & BITS["administrator"]
    assert not any(int(r["permissions"]) & BITS["administrator"] for r in fake.roles.values())


def test_the_stage_exception_is_narrow_one_permission_on_one_kind_of_channel_for_the_owner_roles(layout):
    stage = next(c for c in layout.channels if c.type == "stage")
    rows = {row.target: row for row in stage.overwrites}
    owners = {r.name for r in layout.roles if r.owner}
    holders = {t for t, row in rows.items() if row.allow & perms.BIT["manage_channels"]}
    assert holders == owners
    for row in rows.values():
        assert not row.allow & perms.STRUCTURAL_MASK & ~perms.BIT["manage_channels"]
        for name in ("mute_members", "move_members"):
            assert (row.allow & perms.BIT[name]) == (perms.BIT[name] if row.target in owners else 0)
    assert layout.bot_permissions() & perms.BIT["manage_channels"]
