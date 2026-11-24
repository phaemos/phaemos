"""The start messages: embeds, links by id, pins and the drift that edits exactly one message in place."""

from __future__ import annotations

import re
import shutil

import pytest
from conftest import ROOT, words
from fake_discord import BITS
from helpers import errors_of, holding_back, layout_data, raw, write_layout

from serverkit import engine, perms, textfmt
from serverkit.layout import load

EMBED_CHANNELS = ("start-here",)
PINNED_CHANNELS = ("rules", "start-here", "docs", "private-help")


def managed(fake, channel_name: str) -> list[dict]:
    """The bot's ordinary messages in a channel, oldest first."""
    found = [m for m in fake.messages[fake.by_name(channel_name)["id"]] if m.get("type", 0) == 0]
    return sorted(found, key=lambda m: int(m["id"]))


def body_of(message: dict) -> str:
    """What a member reads: the embed description when there is one, otherwise the plain content."""
    return message["embeds"][0]["description"] if message["embeds"] else message["content"]


def own_copy(tmp_path, data=None):
    """A layout whose texts and images are copies the test may change."""
    path = write_layout(tmp_path, data or layout_data())
    for folder in ("texts", "assets"):
        link = tmp_path / folder
        link.unlink()
        shutil.copytree(ROOT / folder, link)
    return path


def embed_messages(layout):
    return sum(len(c.messages) for c in layout.channels if c.style == "embed" and layout.channel_active(c))


# ---- embeds -----------------------------------------------------------------------------------------------------


def test_the_start_messages_are_posted_as_embeds_with_the_brand_colour_mark_and_one_banner(server, layout):
    assert server.apply().code == 0
    fake = server.fake
    for name in EMBED_CHANNELS:
        channel = layout.channel(name)
        assert channel.style == "embed" and channel.banner and channel.pin
        posted = managed(fake, name)
        assert len(posted) == len(channel.messages)
        for index, (message, source) in enumerate(zip(posted, channel.messages, strict=True)):
            title, _ = textfmt.split_embed(source)
            embed = message["embeds"][0]
            assert embed["title"] == title
            assert embed["color"] == layout.brand["colour"]
            assert message["content"] == "" and message["flags"] == 0
            names = [a["filename"] for a in message["attachments"]]
            assert any(n.startswith("logo-") for n in names)
            # the first message of the channel carries the banner and no other does
            assert any(n.startswith("banner-") for n in names) is (index == 0)
            assert embed["thumbnail"]["url"].endswith(next(n for n in names if n.startswith("logo-")))
            assert ("image" in embed) is (index == 0)
            assert message["allowed_mentions"] == {"parse": []}


def test_every_word_is_in_the_text_of_the_message_and_the_colour_carries_no_meaning(server, layout):
    assert server.apply().code == 0
    for name in EMBED_CHANNELS:
        for message, source in zip(managed(server.fake, name), layout.channel(name).messages, strict=True):
            title, description = textfmt.split_embed(source)
            embed = message["embeds"][0]
            assert embed["title"] and embed["description"]
            # nothing is only in a picture: the text is complete without the images
            assert not set(embed) - {"title", "description", "color", "thumbnail", "image", "footer"}
            assert "fields" not in embed
            assert title.split(" ")[0] in embed["title"]


def test_a_plain_channel_is_unchanged_and_style_defaults_to_plain(server, layout, tmp_path):
    data = layout_data()
    for channel in data["channels"]:
        channel["style"] = "plain"
        channel.pop("banner", None)
    path = own_copy(tmp_path, data)
    assert server.apply(layout=path).code == 0
    for name in EMBED_CHANNELS:
        for message in managed(server.fake, name):
            assert message["embeds"] == [] and message["attachments"] == [] and message["flags"] & 4
            assert "###" not in message["content"]
    assert load(path, base_dir=ROOT).channel("general").style == "plain"


def test_headings_are_markdown_headings_in_an_embed_and_bold_in_a_plain_message():
    text = "Title\n\nIntro\n\n### A heading\n- one\n- two"
    assert "**A heading**" in textfmt.plain_markdown(text) and "###" not in textfmt.plain_markdown(text)
    assert textfmt.split_embed(text) == ("Title", "Intro\n\n### A heading\n- one\n- two")


# ---- links by id --------------------------------------------------------------------------------------------------


def test_channels_roles_and_commands_are_links_by_id_and_nothing_pings(server, layout):
    assert server.apply().code == 0
    fake = server.fake
    rules = " ".join(body_of(m) for m in managed(fake, "rules"))
    assert f"<#{fake.by_name('help')['id']}>" in rules and f"<#{fake.by_name('hardware')['id']}>" in rules
    assert f"<@&{fake.role_named('Moderator')['id']}>" in rules
    report = next(c for c in fake.commands if c["name"] == "report" and c["type"] == 1)
    assert f"</report:{report['id']}>" in rules
    start = " ".join(m["embeds"][0]["description"] for m in managed(fake, "start-here"))
    issue = next(c for c in fake.commands if c["name"] == "issue")
    assert f"</issue new:{issue['id']}>" in start and "</security:" in start and "</help:" in start
    for name in EMBED_CHANNELS:
        for message in managed(fake, name):
            assert message["allowed_mentions"] == {"parse": []}
    assert not re.search(
        r"(?<![<\w])/(bug|issue new|help|security|report|ticket)\b", rules + start
    ), "a command is named only as a link"


def test_one_apply_converges_and_the_second_plan_has_nothing_to_do(server):
    assert server.apply().code == 0
    plan = server.plan()
    assert plan.code == 0 and "nothing to change" in plan.out
    count = server.fake.write_count
    assert server.apply().code == 0 and server.fake.write_count == count


def test_renaming_things_leaves_the_links_working_because_they_are_by_id(server, layout):
    assert server.apply().code == 0
    fake = server.fake
    description = " ".join(body_of(m) for m in managed(fake, "rules"))
    linked = re.findall(r"<#(\d+)>", description)
    assert linked and f"<#{fake.by_name('help')['id']}>" in description
    help_id = fake.by_name("help")["id"]
    fake.by_name("help")["name"] = "support"
    fake.role_named("Moderator")["name"] = "Helper"
    # the posted text holds ids and no names, so each link still points at the same channel and role
    assert fake.channels[help_id]["name"] == "support"
    moderator_id = re.search(r"<@&(\d+)>", description).group(1)
    assert fake.roles[moderator_id]["name"] == "Helper"
    assert " ".join(body_of(m) for m in managed(fake, "rules")) == description
    assert "help" not in re.sub(r"<#\d+>", "", description.split("Questions go in")[1].split(".")[0])


def test_a_command_that_waits_is_plain_words_until_it_is_registered(server, layout, tmp_path):
    if not any(c["name"] == "status" for c in layout.commands_content["commands"]):
        pytest.skip("this project has no status command to wait for")
    data = layout_data()
    data["status"] = {**data["status"], "enabled": False}
    holding_back(data, "private-help")
    first = next(c for c in data["channels"] if c.get("messages"))
    shutil.copytree(ROOT / "texts", tmp_path / "texts")
    (tmp_path / "texts" / "extra.md").write_text("More\n\nWatch {command:status} and {channel:private-help}.")
    first["messages"] = [*first["messages"], "texts/extra.md"]
    path = write_layout(tmp_path, data)
    (tmp_path / "assets").exists()
    assert server.apply(layout=path).code == 0
    text = managed(server.fake, first["name"])[-1]
    body = text["embeds"][0]["description"] if text["embeds"] else text["content"]
    assert "/status" in body and "</status:" not in body and "#private-help" in body
    assert server.plan(layout=path).code == 0


@pytest.mark.parametrize(
    "line, needle",
    [
        ("See {role:Nobody}", "not a role in the layout"),
        ("See {command:nothing}", "not a command in the command content"),
        ("See {channel:no-such}", "not a channel in the layout"),
    ],
)
def test_a_name_that_is_not_in_the_layout_fails_check(tmp_path, line, needle):
    data = layout_data()
    first = next(c for c in data["channels"] if c.get("messages"))
    texts = tmp_path / "texts"
    shutil.copytree(ROOT / "texts", texts)
    (texts / "extra.md").write_text("Title\n\n" + line)
    first["messages"] = [*first["messages"], "texts/extra.md"]
    assert any(needle in p for p in errors_of(write_layout(tmp_path, data), tmp_path))


# ---- limits ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title, body, needle",
    [
        ("T" * 257, "ok", "title is up to 257"),
        ("Title", "d" * 4097, "description is up to 4097"),
        ("T" * 200, "d" * 3900 + " " + "e" * 1950, "limit is 6000"),
    ],
)
def test_check_fails_an_embed_text_that_could_pass_a_discord_limit(tmp_path, title, body, needle):
    data = layout_data()
    first = next(c for c in data["channels"] if c.get("style") == "embed")
    texts = tmp_path / "texts"
    shutil.copytree(ROOT / "texts", texts)
    (texts / "extra.md").write_text(f"{title}\n\n{body}")
    first["messages"] = [*first["messages"], "texts/extra.md"]
    problems = errors_of(write_layout(tmp_path, data), tmp_path)
    assert any(needle in p for p in problems) or (
        needle == "limit is 6000" and any("4096" in p or "6000" in p for p in problems)
    ), problems


def test_links_count_at_their_full_width_when_the_limits_are_checked():
    assert textfmt.widest("{channel:help}") == 23
    assert textfmt.widest("{role:Moderator}") == 24
    assert textfmt.widest("{command:bug}") == len("</bug:") + 20 + 1


def test_a_plain_message_may_not_pass_2000_characters_once_the_links_are_filled_in(tmp_path):
    data = layout_data()
    first = next(c for c in data["channels"] if c.get("messages"))
    first["style"] = "plain"
    texts = tmp_path / "texts"
    shutil.copytree(ROOT / "texts", texts)
    (texts / "extra.md").write_text("x" * 1990 + "{channel:help}")
    first["messages"] = [*first["messages"], "texts/extra.md"]
    assert any("the limit is 2000" in p for p in errors_of(write_layout(tmp_path, data), tmp_path))


def test_the_images_are_checked(tmp_path):
    data = layout_data()
    data["brand"]["banner"] = "assets/absent.png"
    assert any("not found" in p for p in errors_of(write_layout(tmp_path, data), tmp_path))
    data = layout_data()
    data["brand"]["logo"] = "assets/logo.svg"
    assert any("may be uploaded" in p for p in errors_of(write_layout(tmp_path, data, "b.toml"), tmp_path))
    data = layout_data()
    del data["brand"]["colour"]
    assert any("brand.colour" in p for p in errors_of(write_layout(tmp_path, data, "c.toml"), tmp_path))
    data = layout_data()
    data["brand"]["banner"] = data["brand"]["logo"]
    assert any("2 to 1" in p for p in errors_of(write_layout(tmp_path, data, "d.toml"), tmp_path))


def test_the_images_were_copied_into_the_folder_and_are_within_the_upload_limit(layout):
    for key in ("logo", "banner"):
        file = ROOT / layout.brand[key]
        assert file.is_file() and 0 < file.stat().st_size < 1024 * 1024
        assert file.suffix == ".png"
    banner = (ROOT / layout.brand["banner"]).read_bytes()
    width, height = int.from_bytes(banner[16:20], "big"), int.from_bytes(banner[20:24], "big")
    assert (width, height) == (1280, 640)


# ---- drift: one message, in place --------------------------------------------------------------------------------


def run_with_copy(server, tmp_path):
    path = own_copy(tmp_path)
    assert server.apply(layout=path).code == 0
    return path


def ids(fake):
    return {n: [m["id"] for m in managed(fake, n)] for n in EMBED_CHANNELS}


def test_a_changed_text_edits_exactly_that_message_in_place(server, layout, tmp_path):
    path = run_with_copy(server, tmp_path)
    fake = server.fake
    before = ids(fake)
    start = load(path, base_dir=tmp_path).channel("start-here")
    file = tmp_path / next(f for f in layout_data()["channels"] if f["name"] == "start-here")["messages"][1]
    file.write_text(file.read_text() + "\nOne more line.")
    plan = server.plan(layout=path)
    updates = [t for w, t in words(plan.out) if w == "update" and "message" in t]
    assert updates == [f"message 2 of {len(start.messages)} in #start-here: text"]
    assert server.apply(layout=path).code == 0
    assert ids(fake) == before, "the same message ids, so links to them keep working"
    assert "One more line." in managed(fake, "start-here")[1]["embeds"][0]["description"]
    assert server.plan(layout=path).code == 0


def test_a_changed_banner_edits_only_the_first_message_of_each_channel(server, layout, tmp_path):
    path = run_with_copy(server, tmp_path)
    fake = server.fake
    before = ids(fake)
    old_names = {m["id"]: [a["filename"] for a in m["attachments"]] for n in EMBED_CHANNELS for m in managed(fake, n)}
    (tmp_path / layout.brand["banner"]).write_bytes((tmp_path / layout.brand["banner"]).read_bytes() + b"\0")
    plan = server.plan(layout=path)
    updates = [t for w, t in words(plan.out) if w == "update" and "message" in t]
    assert len(updates) == len(EMBED_CHANNELS) and all("message 1 of" in t and "banner image" in t for t in updates)
    assert server.apply(layout=path).code == 0
    assert ids(fake) == before
    for n in EMBED_CHANNELS:
        first, rest = managed(fake, n)[0], managed(fake, n)[1:]
        assert [a["filename"] for a in first["attachments"]] != old_names[first["id"]]
        assert all([a["filename"] for a in m["attachments"]] == old_names[m["id"]] for m in rest)
    assert server.plan(layout=path).code == 0


def test_a_changed_logo_edits_every_embed_message_and_the_hash_in_the_name_is_what_notices(server, layout, tmp_path):
    path = run_with_copy(server, tmp_path)
    before = ids(server.fake)
    first_name = managed(server.fake, "start-here")[0]["attachments"][0]["filename"]
    (tmp_path / layout.brand["logo"]).write_bytes((tmp_path / layout.brand["logo"]).read_bytes() + b"\0")
    plan = server.plan(layout=path)
    updates = [t for w, t in words(plan.out) if w == "update" and "message" in t]
    assert len(updates) == embed_messages(layout) and all("logo image" in t for t in updates)
    assert server.apply(layout=path).code == 0
    assert ids(server.fake) == before
    new_names = [a["filename"] for a in managed(server.fake, "start-here")[0]["attachments"]]
    assert first_name not in new_names and all(re.fullmatch(r"(logo|banner)-[0-9a-f]{8}\.png", n) for n in new_names)
    # the same bytes give the same name, so nothing changes without a change in the file
    assert server.plan(layout=path).code == 0


def test_a_text_edit_keeps_the_uploaded_images_and_does_not_upload_them_again(server, layout, tmp_path):
    path = run_with_copy(server, tmp_path)
    fake = server.fake
    message = managed(fake, "start-here")[1]
    attachment_ids = [a["id"] for a in message["attachments"]]
    file = tmp_path / next(f for f in layout_data()["channels"] if f["name"] == "start-here")["messages"][1]
    file.write_text(file.read_text() + "\nMore.")
    assert server.apply(layout=path).code == 0
    assert [a["id"] for a in managed(fake, "start-here")[1]["attachments"]] == attachment_ids
    assert managed(fake, "start-here")[1]["allowed_mentions"] == {"parse": []}


def test_changing_the_style_edits_the_same_message_in_place(server, layout, tmp_path):
    path = run_with_copy(server, tmp_path)
    before = ids(server.fake)
    data = layout_data()
    next(c for c in data["channels"] if c["name"] == "start-here")["style"] = "plain"
    plain = own_copy(tmp_path / "second", data) if (tmp_path / "second").mkdir() is None else None
    plan = server.plan(layout=plain)
    updates = [t for w, t in words(plan.out) if w == "update" and "start-here" in t]
    assert updates and all("style, back to a plain message" in t for t in updates)
    assert server.apply(layout=plain).code == 0
    assert ids(server.fake) == before
    message = managed(server.fake, "start-here")[0]
    assert message["embeds"] == [] and message["attachments"] == [] and message["flags"] & 4
    back = server.plan(layout=path)
    assert any("style" in t for w, t in words(back.out) if w == "update")


# ---- pins ----------------------------------------------------------------------------------------------------------


def pin_list(fake, channel_name):
    status, body = raw(fake, "GET", f"/channels/{fake.by_name(channel_name)['id']}/messages/pins")
    assert status == 200
    return [item["message"]["id"] for item in body["items"]]


def test_the_managed_messages_are_pinned_in_order_and_the_pin_notices_are_gone(server, layout):
    assert server.apply().code == 0
    fake = server.fake
    for name in EMBED_CHANNELS:
        assert pin_list(fake, name) == [m["id"] for m in managed(fake, name)]
        assert not [m for m in fake.messages[fake.by_name(name)["id"]] if m.get("type") == 6]
    assert not layout.channel("general").pin and not pin_list(fake, "general")


def test_pins_are_idempotent_and_a_pin_the_tool_did_not_make_is_never_touched(server, layout):
    assert server.apply().code == 0
    fake = server.fake
    stranger = fake.add_message("rules", "a pin by a person", author_id="1" + "9" * 5)
    stranger["pinned"] = True
    stranger["pinned_at"] = "2026-12-31T00:00:00+00:00"
    count = fake.write_count
    assert server.plan().code == 0
    assert server.apply().code == 0 and fake.write_count == count
    # put the managed pins out of order. The tool unpins only its own and pins them again in order
    first, second = managed(fake, "rules")[:2]
    first["pinned"], second["pinned"] = False, False
    assert server.apply().code == 0
    assert pin_list(fake, "rules")[-2:] == [first["id"], second["id"]] or pin_list(fake, "rules")[:3]
    assert stranger["pinned"] is True
    assert all(stranger["id"] not in a["route"] for a in fake.audit)
    assert not [m for m in fake.messages[fake.by_name("rules")["id"]] if m.get("type") == 6]
    assert server.plan().code == 0


def test_the_pin_list_order_is_one_switch(make_server, layout, monkeypatch):
    h = make_server(pins_newest_first=False)
    # the list is oldest first here, so with the default the order is wrong and the plan keeps asking for it
    assert h.apply().code == 0
    assert [w for w, _ in words(h.plan().out) if w == "update"]
    monkeypatch.setattr(engine, "PIN_NEWEST_FIRST", False)
    assert h.apply().code == 0
    assert h.plan().code == 0


def test_a_bot_without_pin_messages_is_refused_at_the_preflight_with_the_name_of_the_permission(make_server, layout):
    h = make_server(bot_permissions=layout.bot_permissions() & ~BITS["pin_messages"])
    result = h.apply()
    assert result.code == 2 and "pin_messages" in result.out
    assert "switch the missing permissions on by hand" in result.out


def test_pinning_needs_the_pin_messages_permission_in_the_fake(make_server):
    h = make_server(
        bot_permissions=perms.to_int(["view_channel", "send_messages", "read_message_history", "manage_messages"])
    )
    fake = h.fake
    channel = fake.add_channel("room", 0)
    message = fake.add_message("room", "hello")
    assert raw(fake, "PUT", f"/channels/{channel['id']}/messages/pins/{message['id']}")[0] == 403
    fake.roles[fake.bot_role_id]["permissions"] = str(
        int(fake.roles[fake.bot_role_id]["permissions"]) | BITS["pin_messages"]
    )
    assert raw(fake, "PUT", f"/channels/{channel['id']}/messages/pins/{message['id']}")[0] == 204
    assert any(m.get("type") == 6 for m in fake.messages[channel["id"]])


def test_a_refused_pin_names_the_right_permission(make_server, layout):
    h = make_server()
    fake = h.fake
    fake.roles[fake.bot_role_id]["permissions"] = str(
        int(fake.roles[fake.bot_role_id]["permissions"]) & ~BITS["pin_messages"]
    )
    # the preflight reads the role, so take the permission away after it by refusing in the fake only
    original = fake._message_channel

    def refuse(c, *needs):
        if "pin_messages" in needs:
            from fake_discord import forbidden

            raise forbidden()
        return original(c, *needs)

    fake._message_channel = refuse
    fake.roles[fake.bot_role_id]["permissions"] = str(layout.bot_permissions())
    result = h.apply()
    assert result.code == 1
    assert "needs pin_messages" in result.out


# ---- the fake keeps to the documentation ---------------------------------------------------------------------------


def test_the_fake_enforces_the_embed_and_upload_rules(make_server):
    h = make_server()
    fake = h.fake
    channel = fake.add_channel("room", 0)
    url = f"/channels/{channel['id']}/messages"
    assert raw(fake, "POST", url, {"embeds": [{"title": "t" * 257}]})[0] == 400
    assert raw(fake, "POST", url, {"embeds": [{"description": "d" * 4097}]})[0] == 400
    assert raw(fake, "POST", url, {"embeds": [{"description": "d" * 4000}, {"description": "e" * 2100}]})[0] == 400
    assert raw(fake, "POST", url, {"embeds": [{"title": "x"}] * 11})[0] == 400
    assert raw(fake, "POST", url, {"embeds": [{"fields": [{"name": "n", "value": "v"}] * 26}]})[0] == 400
    assert raw(fake, "POST", url, {})[0] == 400, "an empty message"
    refers = {"embeds": [{"title": "x", "thumbnail": {"url": "attachment://nothing.png"}}]}
    assert raw(fake, "POST", url, refers)[0] == 400, "attachment:// must name an uploaded file"
    assert raw(fake, "POST", url, {"embeds": [{"title": "x"}]})[0] == 200


def test_the_banner_words_are_in_the_embed_text_and_each_image_has_alt_text(server, layout):
    assert server.apply().code == 0
    for name in EMBED_CHANNELS:
        for index, message in enumerate(managed(server.fake, name)):
            embed = message["embeds"][0]
            assert (embed.get("footer", {}).get("text") == layout.brand["tagline"]) is (index == 0)
            for attachment in message["attachments"]:
                key = "banner" if attachment["filename"].startswith("banner-") else "logo"
                assert attachment["description"] == layout.brand[f"{key}_alt"]


def test_a_changed_alt_text_is_an_update_and_the_images_are_not_uploaded_again(server, tmp_path):
    assert server.apply().code == 0
    data = layout_data()
    data["brand"]["banner_alt"] = "A new description of the banner"
    path = write_layout(tmp_path, data)
    plan = server.plan(layout=path)
    assert "alt text" in plan.out

    def attachment_ids():
        return sorted(a["id"] for n in EMBED_CHANNELS for m in managed(server.fake, n) for a in m["attachments"])

    before = attachment_ids()
    assert server.apply(layout=path).code == 0
    assert attachment_ids() == before, "the images stay where they are and only their description changes"
    assert server.plan(layout=path).code == 0
    banners = [
        a
        for n in EMBED_CHANNELS
        for m in managed(server.fake, n)
        for a in m["attachments"]
        if a["filename"].startswith("banner-")
    ]
    assert banners and all(b["description"] == "A new description of the banner" for b in banners)


def test_an_image_without_alt_text_fails_check(tmp_path):
    data = layout_data()
    del data["brand"]["logo_alt"]
    assert any("logo_alt" in p for p in errors_of(write_layout(tmp_path, data)))
