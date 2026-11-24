"""Hostile input: what a stranger can write must never reach Discord as a ping, an invite,
a live link, a disguised string or an oversized message. Each test looks at what the
receiver on 127.0.0.1 was sent."""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_relay_support import FIXTURES, api_env, receiver, relay, run_relay  # noqa: E402,F401

HOSTILE = sorted((FIXTURES / "events").glob("hostile_*.json"))
ZWSP = chr(0x200B)
OWN_LINK = re.compile(r"<https://github\.com/example-org/example/[A-Za-z0-9/._%-]+>")


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def posted(path, receiver, tmp_path):
    recorded = json.loads(path.read_text())
    run = run_relay(
        tmp_path, recorded["event_name"], recorded["payload"], receiver, extra_env=api_env(recorded, receiver)
    )
    assert run.code == 0
    return run, receiver.posts()


def test_there_are_hostile_fixtures_for_every_kind_of_stranger_text():
    names = {path.stem for path in HOSTILE}
    for wanted in (
        "hostile_issue_long_title",
        "hostile_issue_mentions",
        "hostile_issue_markdown",
        "hostile_issue_rtl",
        "hostile_issue_author_markup",
        "hostile_announcement_body",
        "hostile_announcement_open_fence_long",
        "hostile_release_open_fence",
        "hostile_discussion_title",
        "hostile_push_subject",
    ):
        assert wanted in names


@pytest.mark.parametrize("path", HOSTILE, ids=lambda p: p.stem)
def test_nothing_can_ping_link_or_disguise(path, receiver, tmp_path):
    run, posts = posted(path, receiver, tmp_path)
    if path.stem.endswith("_held"):
        assert posts == [], "text from a stranger is never broadcast before a maintainer acts"
        return
    assert posts, "a hostile post is still posted, only made safe"
    for post in posts:
        payload = post["payload"]
        assert payload["allowed_mentions"] == {"parse": []}
        for text in strings(payload):
            # no mention can be written: every at sign is followed by a zero width space
            for bad in re.finditer(r"@(?!" + ZWSP + ")", text):
                # the only bare at signs allowed are inside fenced or inline code
                before = text[: bad.start()]
                assert before.count("```") % 2 == 1 or before.count("`") % 2 == 1 or before.count("~~~~") % 2 == 1, text
            # no hidden or reordering character and no control character
            for char in text:
                if char == "\n":
                    continue
                assert unicodedata.category(char) not in ("Cc", "Cs", "Co") and not (
                    unicodedata.category(char) == "Cf" and char != ZWSP
                ), (hex(ord(char)), text[:80])
            # no invite anywhere
            assert not re.search(r"discord\.gg|discord(?:app)?\.com/invite|dsc\.gg|discord\.me", text, re.I)
            # every angle bracket pair is one of our own links
            cleaned = OWN_LINK.sub("", text)
            if "```" not in text:
                assert "<" not in cleaned and ">" not in re.sub(r"(?m)^>", "", cleaned), text[:200]
        # every live markdown link points at GitHub
        for text in strings(payload):
            for target in re.findall(r"\]\((https?://[^)\s]*)\)", text):
                assert relay.host_of(target) == "github.com", target
        assert len(payload["content"]) <= 2000
        for embed in payload.get("embeds", []):
            assert len(embed["title"]) <= 256 and len(embed["description"]) <= 3800
            relay.check_embed(embed)
            assert (
                len(embed["title"])
                + len(embed["description"])
                + sum(len(f["name"]) + len(f["value"]) for f in embed.get("fields", []))
                + len(embed["footer"]["text"])
                <= 6000
            )
            assert all(len(f["value"]) <= 1024 and len(f["name"]) <= 256 for f in embed.get("fields", []))


@pytest.mark.parametrize("path", HOSTILE, ids=lambda p: p.stem)
def test_code_fences_in_every_post_are_balanced(path, receiver, tmp_path):
    _, posts = posted(path, receiver, tmp_path)
    for post in posts:
        for embed in post["payload"].get("embeds", []):
            assert relay.open_fence(embed["description"]) == ""


def test_a_5000_character_title_is_cut_to_200_with_three_dots(receiver, tmp_path):
    _, posts = posted(FIXTURES / "events" / "hostile_issue_long_title.json", receiver, tmp_path)
    content = posts[0]["payload"]["content"]
    title = content.removeprefix("New issue #900: ").split(". <https")[0]
    assert title == "A" * 197 + "..."
    assert len(content) < 400


def test_a_title_made_of_mentions_pings_nobody_and_shows_no_mention(receiver, tmp_path):
    _, posts = posted(FIXTURES / "events" / "hostile_issue_mentions.json", receiver, tmp_path)
    content = posts[0]["payload"]["content"]
    assert posts[0]["payload"]["allowed_mentions"] == {"parse": []}
    assert "@everyone" not in content and "@here" not in content and "<@" not in content and "<#" not in content
    assert "everyone" in content  # the words stay readable


def test_markdown_in_a_title_cannot_make_a_link_or_leave_formatting_open(receiver, tmp_path):
    _, posts = posted(FIXTURES / "events" / "hostile_issue_markdown.json", receiver, tmp_path)
    content = posts[0]["payload"]["content"]
    assert "evil.example" not in content
    # every markdown character from the title is escaped, so nothing stays open
    title = content.removeprefix("New issue #902: ").rsplit(". <https", 1)[0]
    for char in "*_~`|[]":
        for found in re.finditer(re.escape(char), title):
            backslashes = len(title[: found.start()]) - len(title[: found.start()].rstrip("\\"))
            assert backslashes % 2 == 1, (char, title)
    assert content.endswith("issues/902>")


def test_right_to_left_overrides_and_zero_width_characters_are_gone(receiver, tmp_path):
    _, posts = posted(FIXTURES / "events" / "hostile_issue_rtl.json", receiver, tmp_path)
    content = posts[0]["payload"]["content"]
    assert (
        content
        == "New issue #903: Invoice gnp.exe hidden zerowidth join end. <https://github.com/example-org/example/issues/903>"
    )


def test_an_invite_link_in_a_body_is_removed(receiver, tmp_path):
    _, posts = posted(FIXTURES / "events" / "hostile_announcement_body.json", receiver, tmp_path)
    description = posts[0]["payload"]["embeds"][0]["description"]
    assert "invite link removed" in description
    assert not re.search(r"discord\.gg|invite/", description)
    assert "(link to evil.example)" in description and "[a safe one](https://github.com/" in description
    assert description.endswith("[Read the full post](https://github.com/example-org/example/discussions/920)")


def test_an_author_name_with_markup_never_appears(receiver, tmp_path):
    _, posts = posted(FIXTURES / "events" / "hostile_issue_author_markup.json", receiver, tmp_path)
    raw = json.dumps(posts)
    assert "bob" not in raw and "evil.test" not in raw
    assert "author" not in raw.replace("authority", "")


def test_a_commit_author_name_never_appears_in_a_merged_change_line(receiver, tmp_path):
    recorded = json.loads((FIXTURES / "events" / "push_single_feat.json").read_text())
    recorded["payload"]["commits"][0]["author"]["name"] = "**Mallory** @everyone"
    recorded["payload"]["sender"]["login"] = "mallory-the-user"
    run_relay(tmp_path, recorded["event_name"], recorded["payload"], receiver)
    assert "Mallory" not in json.dumps(receiver.posts()) and "mallory" not in json.dumps(receiver.posts())


def test_a_hostile_label_is_not_shown_unless_it_is_on_the_list(receiver, tmp_path):
    _, posts = posted(FIXTURES / "events" / "hostile_issue_labels.json", receiver, tmp_path)
    assert "Labels: bug, security." in posts[0]["payload"]["content"]
    assert "**" not in posts[0]["payload"]["content"] and "everyone" not in posts[0]["payload"]["content"]


def test_a_newline_in_a_title_cannot_start_a_workflow_command(receiver, tmp_path):
    run, posts = posted(FIXTURES / "events" / "hostile_issue_newlines.json", receiver, tmp_path)
    assert "\n" not in posts[0]["payload"]["content"]
    assert "injected" not in run.out and "injected" not in run.summary
    for line in run.out.splitlines():
        assert line.startswith("relay: ") or line.startswith("::notice title=Discord relay::")


def test_a_hostile_title_is_not_printed_in_the_log_or_the_summary(receiver, tmp_path):
    run, _ = posted(FIXTURES / "events" / "hostile_discussion_title.json", receiver, tmp_path)
    assert "Heading" not in run.out and "Heading" not in run.summary


def test_a_hostile_tag_cannot_break_the_release_link(receiver, tmp_path):
    _, posts = posted(FIXTURES / "events" / "hostile_release_tag.json", receiver, tmp_path)
    embed = posts[0]["payload"]["embeds"][0]
    assert re.fullmatch(r"https://github\.com/example-org/example/releases/tag/[A-Za-z0-9._%-]+", embed["url"])
    assert " " not in embed["url"] and "(" not in embed["url"]
    assert "everyone" in embed["title"] and "@everyone" not in embed["title"]


def test_a_very_long_release_tag_still_fits_every_limit(receiver, tmp_path):
    recorded = json.loads((FIXTURES / "events" / "release_stable.json").read_text())
    recorded["payload"]["release"]["tag_name"] = "v" + "9" * 3000
    recorded["payload"]["release"]["body"] = "x " * 5000
    run = run_relay(tmp_path, recorded["event_name"], recorded["payload"], receiver)
    payload = receiver.posts()[0]["payload"]
    embed = payload["embeds"][0]
    assert run.code == 0
    assert len(payload["content"]) <= 2000 and len(embed["title"]) <= 256 and len(embed["fields"][0]["value"]) <= 1024
    relay.check_embed(embed)


def test_an_event_that_is_not_an_object_is_refused_without_posting(receiver, tmp_path):
    run = run_relay(tmp_path, "issues", ["not", "an", "object"], receiver)
    assert run.code == 2 and receiver.requests == []
