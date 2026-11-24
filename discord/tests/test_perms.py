"""The permission arithmetic: bit values, resolution order and the numbers the specification gives."""

from __future__ import annotations

import pytest
from fake_discord import ALL, BITS

from serverkit import perms


def test_bit_table_agrees_with_the_fake():
    assert perms.BIT == BITS


def test_integers_from_the_specification(layout):
    assert layout.everyone == 311452355648
    assert layout.sets["moderator"] == 2252899459538944
    assert layout.sets["moderator"] | layout.sets["maintainer"] == 7337066996310150
    # the specification counts 27 for a bot that also held the owner's roles' permissions. Now the owner makes
    # Maintainer and Moderator by hand, so the bot holds what it needs for its own work and for the staff channels and the stage, 26 in all
    assert set(perms.names_of(layout.bot_permissions())) == {
        "add_reactions",
        "attach_files",
        "change_nickname",
        "connect",
        "create_private_threads",
        "create_public_threads",
        "embed_links",
        "manage_channels",
        "manage_guild",
        "manage_messages",
        "manage_roles",
        "manage_threads",
        "manage_webhooks",
        "moderate_members",
        "move_members",
        "mute_members",
        "pin_messages",
        "read_message_history",
        "request_to_speak",
        "send_messages",
        "send_messages_in_threads",
        "speak",
        "stream",
        "use_application_commands",
        "use_vad",
        "view_channel",
    }


def test_bot_never_needs_administrator_or_the_withheld_set(layout):
    needed = layout.bot_permissions()
    for name in ("administrator", "manage_guild_expressions", "create_instant_invite", "priority_speaker"):
        assert not needed & perms.BIT[name], name


def test_names_round_trip():
    value = perms.to_int(["view_channel", "send_messages", "pin_messages"])
    assert perms.names_of(value) == ["view_channel", "send_messages", "pin_messages"]


def test_unknown_permission_is_refused():
    with pytest.raises(perms.UnknownPermission):
        perms.to_int(["fly"])


def test_order_everyone_then_role_denies_then_role_allows():
    base = perms.to_int(["view_channel", "send_messages", "add_reactions"])
    everyone = (0, perms.to_int(["send_messages"]))
    roles = [(perms.to_int(["send_messages"]), 0), (0, perms.to_int(["add_reactions"]))]
    value = perms.channel_permissions(base, everyone, roles)
    # the role allow wins over the everyone deny. The role deny removes the reaction
    assert value & perms.BIT["send_messages"]
    assert not value & perms.BIT["add_reactions"]


def test_a_deny_on_one_role_is_not_cancelled_by_another_roles_server_wide_permission():
    base = perms.to_int(["view_channel", "manage_messages", "send_messages"])
    value = perms.channel_permissions(base, None, [(0, perms.to_int(["manage_messages"]))])
    assert not value & perms.BIT["manage_messages"]


def test_view_channel_deny_removes_everything():
    base = perms.to_int(["view_channel", "send_messages", "read_message_history"])
    assert perms.channel_permissions(base, (0, perms.BIT["view_channel"]), []) == 0


def test_no_send_removes_the_riders():
    base = perms.to_int(["view_channel", "embed_links", "attach_files", "mention_everyone", "add_reactions"])
    value = perms.channel_permissions(base, None, [])
    assert value == perms.to_int(["view_channel", "add_reactions"])


def test_administrator_skips_everything():
    base = perms.BIT["administrator"]
    assert perms.channel_permissions(base, (0, perms.BIT["view_channel"]), []) == perms.ALL_PERMISSIONS
    assert perms.base_permissions(0, [base]) == perms.ALL_PERMISSIONS == ALL


def test_script_and_fake_agree_in_every_channel_of_a_built_server(server, layout):
    assert server.apply().code == 0
    fake = server.fake
    roles = {r.name: fake.role_named(r.name)["id"] for r in layout.roles}
    for channel in fake.channels.values():
        if channel["type"] == 4:
            continue
        rows = {o["id"]: (int(o["allow"]), int(o["deny"])) for o in channel["permission_overwrites"]}
        for names in ([], ["Moderator"], ["Maintainer"], ["Contributor"], ["Moderator", "Maintainer"]):
            ids = [roles[n] for n in names]
            base = perms.base_permissions(
                int(fake.roles[fake.guild_id]["permissions"]), [int(fake.roles[i]["permissions"]) for i in ids]
            )
            mine = perms.channel_permissions(base, rows.get(fake.guild_id), [rows[i] for i in ids if i in rows])
            assert mine == fake.in_channel(channel, ids), (channel["name"], names)
