"""Unit tests for the text rules of the relay: tables, links, code, mentions and cutting."""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_relay_support import LAYOUT, relay  # noqa: E402

CFG = relay.load_config(str(LAYOUT))
URL = "https://github.com/example-org/example/releases/tag/v1"
ZWSP = chr(0x200B)


def body(text, label="Read the full notes", limit=3800):
    return relay.prepare_body(text, CFG, URL, label, limit)


def test_line_endings_are_normalised():
    assert body("one\r\ntwo\rthree").startswith("one\ntwo\nthree")


def test_tables_become_lists_and_the_header_is_dropped():
    text = "Intro\n\n| Part | Note |\n| --- | --- |\n| Vibration | within 2 percent |\n| Temperature | reads high |\n\nAfter"
    out = body(text)
    assert "- **Vibration** - within 2 percent" in out
    assert "- **Temperature** - reads high" in out
    assert "Part" not in out
    assert out.count("|") == 0


def test_a_rule_or_heading_underline_is_not_a_table():
    out = body("Title with pipe | in it\n---\n\ntext")
    assert "Title with pipe | in it\n---" in out


def test_issue_numbers_become_links_outside_code_and_links():
    out = body(
        "Fixes #12 and `#13` and [see #14](https://github.com/example-org/example/issues/14).\n\n```\n#15\n```\n\nword#16"
    )
    assert "[#12](https://github.com/example-org/example/issues/12)" in out
    assert "`#13`" in out
    assert "[see #14](https://github.com/example-org/example/issues/14)" in out
    assert "\n#15\n" in out
    assert "word#16" in out
    assert "[#14]" not in out and "[#15]" not in out


def test_fenced_blocks_and_inline_code_are_never_rewritten():
    text = "```\n| a | b |\n|---|---|\n| @everyone | <@1234> |\n![x](http://e.test) https://evil.test discord.gg/abc\n```\n\n`@everyone <@1234>`"
    out = body(text)
    assert "| @everyone | <@1234> |" in out
    assert "![x](http://e.test) https://evil.test discord.gg/abc" in out
    assert "`@everyone <@1234>`" in out


def test_html_comments_are_removed_and_the_cut_marker_cuts():
    assert "secret note" not in body("before <!-- secret note --> after")
    out = body("kept\n\n<!-- discord-cut -->\n\nleft on GitHub")
    assert "left on GitHub" not in out and out.startswith("kept")
    assert "unclosed" not in body("a\n\n<!-- unclosed comment hides the rest")


def test_images_become_their_alt_text_and_nothing_is_fetched():
    out = body(
        "![Three boards](https://example.test/a.png) ![](https://example.test/b.png) <img src='x' alt='html alt'>"
    )
    assert "[Image: Three boards]" in out and "[Image]" in out and "[Image: html alt]" in out
    assert "example.test" not in out


def test_callouts_become_plain_quotes():
    out = body("> [!NOTE]\n> Careful here.\n\n> [!WARNING]\n> Really.")
    assert "> Note:\n> Careful here." in out and "> Warning:" in out
    assert "[!" not in out


@pytest.mark.parametrize(
    "text",
    ["@everyone", "@here", "<@1234>", "<@&5678>", "<#9012>", "<:wave:3>", "<a:wave:3>", "</ban:1>", "<t:170:R>"],
)
def test_mentions_and_discord_markers_are_made_inert(text):
    out = body(f"before {text} after")
    assert "@everyone" not in out and "@here" not in out
    for marker in ("<@", "<#", "<:", "<a:", "</", "<t:"):
        assert marker not in out


def test_invite_links_are_removed_in_every_form():
    out = body(
        "https://discord.gg/abc [x](https://discord.com/invite/y) <https://discordapp.com/invite/z> discord.gg/q dsc.gg/w "
        "http://www.discord.com/invite/k"
    )
    for fragment in ("discord.gg", "invite/", "dsc.gg"):
        assert fragment not in out


def test_links_are_limited_to_the_allowed_hosts():
    out = body(
        "[ok](https://github.com/example-org/example) [sub](https://docs.github.com/x) [bad](https://evil.example/p) "
        "[spoof](https://github.com@evil.example/) [near](https://github.com.evil.example/) [js](javascript:alert(1)) "
        "https://tracker.example/a <https://other.example/b>"
    )
    assert "[ok](https://github.com/example-org/example)" in out
    assert "[sub](https://docs.github.com/x)" in out
    assert "evil.example" not in out.replace("(link to evil.example)", "").replace(
        "(link to github.com.evil.example)", ""
    )
    assert "](https://evil" not in out and "javascript" not in out
    assert "(link to tracker.example)" in out and "(link to other.example)" in out


def test_extra_hosts_from_the_layout_are_allowed():
    cfg = relay.load_config(str(LAYOUT))
    cfg.link_hosts = ["docs.example.test"]
    out = relay.prepare_body(
        "[docs](https://docs.example.test/a) [sub](https://x.docs.example.test/b)", cfg, URL, "More"
    )
    assert "[docs](https://docs.example.test/a)" in out and "[sub](https://x.docs.example.test/b)" in out


def test_stray_brackets_cannot_open_a_link():
    out = body("[never closed and then (http://x.test)")
    assert "\\[never" in out


def test_a_cut_text_ends_with_the_link_and_stays_inside_the_limit():
    text = "\n\n".join(f"Paragraph {i} " + "word " * 40 for i in range(60))
    out = body(text, limit=1000)
    assert len(out) <= 1000
    assert out.endswith(f"[Read the full notes]({URL})")
    assert "\n\n[Read" in out
    assert "Paragraph 59" not in out


def test_the_cut_falls_on_a_paragraph_break():
    text = "A" * 100 + "\n\n" + "B" * 100 + "\n\n" + "C" * 900
    out = body(text, limit=450)
    assert "A" * 100 in out and "B" * 100 in out and "C" not in out


def test_a_code_block_that_is_cut_is_closed():
    text = "Intro\n\n```python\n" + "line\n" * 500
    out = body(text, limit=500)
    assert out.count("```") % 2 == 0
    assert len(out) <= 500


def test_an_unclosed_fence_is_closed_even_when_nothing_is_cut():
    out = body("Intro\n\n~~~~text\nnever closed")
    assert "never closed\n~~~~\n\n[Read" in out


def test_the_link_is_the_whole_description_for_an_empty_body():
    assert body(None) == f"[Read the full notes]({URL})"
    assert body("   \n ") == f"[Read the full notes]({URL})"


def test_one_hard_cut_never_leaves_a_link_open():
    text = "x" * 440 + "[a link that would be cut](https://github.com/example-org/example)"
    out = body(text, limit=490)
    head = out.rsplit("\n\n", 1)[0]
    assert head.count("[") == head.count("]")


@pytest.mark.parametrize(
    "text",
    [
        "A" + chr(0x202E) + "B",
        "A" + chr(0x2066) + "B" + chr(0x2069),
        "A" + chr(0x200B) + "B",
        "A" + chr(0x200D) + "B",
        "A" + chr(0xFEFF) + "B",
        "A" + chr(0x061C) + "B",
        "A\u0007B",
        "A\x1b[31mB",
        "A" + chr(0x2028) + "B",
    ],
)
def test_control_format_and_bidirectional_characters_are_dropped(text):
    out = relay.single_line(text)
    assert all(unicodedata.category(c) not in ("Cc", "Cf", "Cs") for c in out)
    assert out.startswith("A") and "B" in out


def test_plain_text_is_inert():
    out = relay.plain("*bold* _it_ ~~s~~ `c` ||sp|| [l](u) <@1> @all", 200)
    for raw in ("*bold*", "_it_", "~~s~~", "`c`", "||sp||", "[l](u)", "<@1>"):
        assert raw not in out
    assert "@" + ZWSP + "all" in out


def test_plain_cuts_with_three_dots_before_escaping():
    out = relay.plain("x" * 500, 200)
    assert out == "x" * 197 + "..."
    assert relay.plain("short", 200) == "short"


def test_embed_titles_count_their_escapes_against_the_limit():
    out = relay.fit_title("*" * 500, 256)
    assert len(out) <= 256
    assert relay.fit_title("a title", 256) == "a title"


def test_links_in_a_one_line_title_are_removed():
    out = relay.plain("see https://evil.example/x and discord.gg/abc and www.evil.test", 200)
    assert "evil" not in out and "discord.gg" not in out


def test_written_dates_use_uk_month_names():
    assert relay.written_date("2026-11-30T10:00:00Z") == "30 November 2026"
    assert relay.written_date("2026-12-02T10:00:00Z") == "2 December 2026"
    assert relay.parse_time("2026-11-30T10:00:00+01:00") == "2026-11-30T09:00:00Z"
    assert relay.parse_time("not a date") is None and relay.parse_time(None) is None
