"""The staff-roles command: set the owner's roles up once, then leave them to the owner."""

from __future__ import annotations

from conftest import words
from fake_discord import BITS
from helpers import methods

from serverkit import perms


def setup_server(make_server, layout):
    return make_server(owner_roles=False, bot_permissions=layout.bot_permissions(staff_setup=True))


def owner_names(layout):
    return [r.name for r in layout.roles if r.owner]


def expected(fake, role):
    held = fake.bot_base()
    return role.permissions & held & ~perms.OWNER_ONLY_MASK


def test_a_dry_run_prints_what_it_would_do_and_changes_nothing(make_server, layout):
    h = setup_server(make_server, layout)
    before = h.fake.state()
    result = h.run("staff-roles")
    assert result.code == 0
    assert "Mode: dry run. Nothing is changed. Add --apply to make these changes." in result.out
    for name in owner_names(layout):
        assert f'create     role "{name}"' in result.out
    assert methods(h.fake) == set() and h.fake.state() == before
    assert "For you, in this order" not in result.out


def test_it_creates_both_roles_with_exactly_the_permissions_the_bot_holds(make_server, layout):
    h = setup_server(make_server, layout)
    result = h.run("staff-roles", "--apply")
    assert result.code == 0, result.out + result.err
    fake = h.fake
    for role in (r for r in layout.roles if r.owner):
        built = fake.role_named(role.name)
        assert int(built["permissions"]) == expected(fake, role), role.name
        assert not int(built["permissions"]) & perms.OWNER_ONLY_MASK
        assert (
            built["hoist"] is role.hoist and built["mentionable"] is role.mentionable and built["color"] == role.colour
        )
        # a new role lands at the bottom and can tie with the bot's own role. The owner drags it above
        assert built["position"] <= fake.roles[fake.bot_role_id]["position"]
    assert all(a["reason"].startswith(f"{layout.name} layout {layout.hash8}: set up the ") for a in fake.audit)
    assert len(fake.audit) == len(owner_names(layout))


def test_it_prints_the_owner_list_in_the_promised_order(make_server, layout):
    h = setup_server(make_server, layout)
    out = h.run("staff-roles", "--apply").out
    tail = out.split("For you, in this order:")[1].strip().splitlines()
    assert tail[0].startswith("1. Drag Maintainer and Moderator above the bot's role NOW")
    assert "anyone holding the bot's token could edit them" in tail[0]
    assert tail[1].startswith("2. Switch on by hand the permissions the bot could not set.")
    for name in ("Kick, Approve, and Reject Members", "Ban Members", "Mention @everyone, @here, and All Roles"):
        assert name in tail[1]
    assert tail[2].startswith("3. Give yourself Maintainer.")
    assert tail[3].startswith("4. Run ") and "serverkit plan" in tail[3]


def test_it_fills_in_a_role_that_is_below_the_bot_and_keeps_what_the_owner_switched_on(make_server, layout):
    h = setup_server(make_server, layout)
    fake = h.fake
    role = fake.add_role("Maintainer", perms.BIT["kick_members"], position=1)
    fake.roles[fake.bot_role_id]["position"] = 5
    result = h.run("staff-roles", "--apply")
    assert result.code == 0, result.out + result.err
    want = layout.role("Maintainer")
    built = fake.roles[role["id"]]
    assert int(built["permissions"]) == expected(fake, want) | perms.BIT["kick_members"]
    assert built["hoist"] is want.hoist
    assert 'update     role "Maintainer"' in result.out
    # kick was already on, so it is not asked of the owner again
    assert "Kick, Approve" not in result.out.split("Maintainer:")[1].split(";")[0]


def test_it_leaves_a_role_at_or_above_the_bot_alone_and_says_so(make_server, layout):
    h = setup_server(make_server, layout)
    fake = h.fake
    fake.roles[fake.bot_role_id]["position"] = 1
    for name in reversed(owner_names(layout)):
        fake.add_role(name, perms.BIT["manage_messages"])
    before = fake.state()
    result = h.run("staff-roles", "--apply")
    assert result.code == 0
    assert result.out.count("sits at or above the bot's role. That is the finished state") == len(owner_names(layout))
    assert fake.state() == before and methods(fake) == set()


def test_it_gives_no_role_to_any_member_and_moves_nothing(make_server, layout):
    h = setup_server(make_server, layout)
    fake = h.fake
    order = {r["name"]: r["position"] for r in fake.roles.values()}
    h.run("staff-roles", "--apply")
    assert not [r for r in fake.requests if "/members" in r[1] and r[0] != "GET"]
    assert not [r for r in fake.requests if r[0] in ("DELETE",)]
    assert fake.bot_member_roles == [fake.bot_role_id]
    for name, position in order.items():
        assert next(r for r in fake.roles.values() if r["name"] == name)["position"] <= position + len(
            owner_names(layout)
        )


def test_a_second_run_is_a_no_op(make_server, layout):
    h = setup_server(make_server, layout)
    h.run("staff-roles", "--apply")
    count = h.fake.write_count
    second = h.run("staff-roles", "--apply")
    assert second.code == 0 and h.fake.write_count == count
    assert not [w for w, _ in words(second.out) if w in ("create", "update")]


def test_plan_and_apply_still_refuse_until_the_bot_is_below_both_roles_and_say_what_is_outstanding(make_server, layout):
    h = setup_server(make_server, layout)
    h.run("staff-roles", "--apply")
    plan = h.plan()
    assert plan.code == 2
    assert 'If "serverkit staff-roles" has been run, the drag is the step outstanding' in plan.out
    assert h.apply().code == 2
    # the owner drags the two roles above the bot's role and switches on the rest by hand
    h.owner_roles()
    assert h.plan().code in (0, 4)
    assert h.apply().code == 0


def test_plan_and_apply_never_write_an_owner_role_and_staff_roles_does_so_only_while_the_role_is_below_the_bot(
    make_server, layout
):
    h = setup_server(make_server, layout)
    fake = h.fake
    h.run("staff-roles", "--apply")
    ids = {r["id"] for r in fake.roles.values() if r["name"] in owner_names(layout)}
    written_by_staff_roles = len(fake.audit)
    h.owner_roles()
    assert h.apply().code == 0
    after = [a for a in fake.audit[written_by_staff_roles:] if any(i in a["route"] for i in ids)]
    assert after == []
    # and with a role above the bot the command writes nothing at all
    count = fake.write_count
    h.run("staff-roles", "--apply")
    assert fake.write_count == count


def test_the_invite_asks_for_what_the_roles_need_unless_told_not_to(make_server, layout):
    h = make_server()
    big = h.run("invite-url").out
    small = h.run("invite-url", "--no-staff-setup").out
    assert f"permissions={layout.bot_permissions(staff_setup=True)}" in big
    assert f"permissions={layout.bot_permissions()}" in small
    assert layout.bot_permissions(staff_setup=True) & ~layout.bot_permissions()
    for name in perms.OWNER_ONLY:
        assert not layout.bot_permissions(staff_setup=True) & BITS[name]
    assert not layout.bot_permissions(staff_setup=True) & BITS["administrator"]


def test_staff_roles_refuses_a_bot_without_manage_roles(make_server, layout):
    h = make_server(owner_roles=False, bot_permissions=perms.BIT["view_channel"])
    result = h.run("staff-roles", "--apply")
    assert result.code == 2 and "Manage Roles" in result.err
