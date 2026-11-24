"""A server built by the earlier script and the documented way of keeping it."""

from __future__ import annotations

from fake_discord import BITS, TEXT
from helpers import deletes, find, layout_data, methods, only_words, write_layout

CHANGES = ("create", "update", "delete", "rename", "rotate")


def old_server(make_server, layout):
    h = make_server(owner_roles=False)
    fake = h.fake
    fake.roles[fake.bot_role_id]["position"] = 30
    admin = fake.add_role("Admin", BITS["administrator"], position=6)
    fake.add_role("Maintainer", 0, position=5)
    fake.add_role("Contributor", 0, position=4)
    fake.add_role("Member", 0, position=3)
    bot = fake.add_role("Bot", 0, position=2)
    fake.roles[fake.role_named("Contributor")["id"]]["color"] = 0x2ECC71
    fake.bot_member_roles.append(bot["id"])
    hide = [
        {"id": fake.guild_id, "type": 0, "allow": "0", "deny": str(BITS["view_channel"])},
        {"id": admin["id"], "type": 0, "allow": str(BITS["view_channel"]), "deny": "0"},
        {"id": bot["id"], "type": 0, "allow": str(BITS["view_channel"]), "deny": "0"},
    ]
    for category in (layout.name, "Support", "Hardware", "Community"):
        fake.add_channel(category, 4)
    fake.add_channel("Admin", 4, overwrites=hide)
    for name in ("announcements", "general", "releases"):
        fake.add_channel(name, TEXT, parent=layout.name)
    for name in ("help", "bugs", "feature-requests"):
        fake.add_channel(name, TEXT, parent="Support")
    for name in ("esp32", "stm32", "arduino-nano", "pico-w"):
        fake.add_channel(name, TEXT, parent="Hardware")
    for name in ("show-and-tell", "ideas"):
        fake.add_channel(name, TEXT, parent="Community")
    fake.add_channel("bot-logs", TEXT, parent="Admin", overwrites=hide)
    fake.add_channel("moderation", TEXT, parent="Admin", overwrites=hide)
    return h


def migrated_layout(tmp_path):
    data = layout_data()
    find(data["channels"], "mod-log")["previous_names"] = ["bot-logs"]
    find(data["channels"], "moderator-only")["previous_names"] = ["moderation"]
    return write_layout(tmp_path, data)


def test_the_old_text_help_channel_is_a_conflict_and_nothing_changes(make_server, layout):
    h = old_server(make_server, layout)
    h.owner_roles()
    before = h.fake.state()
    result = h.apply()
    assert result.code == 2
    assert "help" in result.err and "Rename or remove the old one by hand" in result.err
    assert h.fake.state() == before and methods(h.fake) == set()


def test_after_the_documented_steps_the_old_server_is_converted_and_then_idempotent(make_server, layout, tmp_path):
    h = old_server(make_server, layout)
    fake = h.fake
    # the owner's steps: make Maintainer and Moderator right by hand and put the bot's role below them, rename
    # the old help and ideas out of the way and remove the Admin role
    h.owner_roles()
    fake.by_name("help")["name"] = "help-old"
    fake.by_name("ideas")["name"] = "ideas-old"
    gone = fake.role_named("Admin")["id"]
    del fake.roles[gone]
    for channel in fake.channels.values():
        # Discord drops a deleted role's rows from every channel
        channel["permission_overwrites"] = [o for o in channel["permission_overwrites"] if o["id"] != gone]
    path = migrated_layout(tmp_path)

    plan = h.plan(layout=path)
    assert plan.code == 3, plan.out  # the renames are held back
    first = h.apply("--allow-renames", layout=path, tty=True, stdin=layout.name + "\n")
    assert first.code == 0, first.out + first.err
    names = {c["name"] for c in fake.channels.values()}
    assert {"mod-log", "moderator-only", "help", "general"} <= names
    assert not names & {"bot-logs", "moderation"}
    # the old things nobody asked to remove are still there, listed and left alone
    assert {"bugs", "esp32", "help-old", "ideas-old"} <= names
    assert fake.by_name("general")["parent_id"] == fake.by_name("Community", 4)["id"]
    assert fake.role_named("Contributor")["color"] == 0

    after = h.plan(layout=path)
    assert after.code == 0, after.out
    assert not only_words(after.out, *CHANGES, "blocked")
    assert any("help-old" in t for w, t in __import__("conftest").words(after.out) if w == "unmanaged")
    before = fake.state()
    again = h.apply(layout=path)
    assert again.code == 0 and fake.state() == before
    assert deletes(fake) == []


def test_an_unmanaged_role_that_holds_administrator_is_a_warning(make_server, layout):
    h = old_server(make_server, layout)
    fake = h.fake
    fake.by_name("help")["name"] = "help-old"
    fake.by_name("ideas")["name"] = "ideas-old"
    h.owner_roles()
    result = h.plan()
    assert any(
        "Admin" in t and "Administrator" in t for w, t in __import__("conftest").words(result.out) if w == "warning"
    )


def test_a_server_with_extra_things_people_made_is_left_as_it_is_after_apply(server, layout):
    fake = server.fake
    fake.add_channel("people-made", TEXT)
    fake.add_role("People made", 0, position=2)
    assert server.apply().code == 0
    before = fake.state()
    assert server.plan().code == 0
    assert server.apply().code == 0
    assert fake.state() == before
    assert any(c["name"] == "people-made" for c in fake.channels.values())
