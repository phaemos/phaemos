"""The layout file: what is accepted and what `check` refuses."""

from __future__ import annotations

import re
import shutil

import pytest
from conftest import ROOT, layout_path
from helpers import dump, errors_of, find, holding_back, layout_data, write_layout

from serverkit import cli
from serverkit.layout import load, style_errors
from serverkit.style import style_problems


def test_the_real_layout_is_valid_and_follows_the_text_rules(layout):
    assert style_errors(layout) == []
    assert layout.name
    # the day one shape from the specification
    active = [c.name for c in layout.active_channels]
    assert "rules" in active
    assert "mod-log" in active
    assert [c.type for c in layout.active_channels if c.name == "help"] == ["forum"]


def test_channels_inherit_their_category_and_replace_a_row_for_the_same_target(layout):
    rules = layout.channel("rules")
    assert [o.target for o in rules.overwrites] == ["@everyone", "@bot"]
    announcements = layout.channel("announcements")
    everyone = next(o for o in announcements.overwrites if o.target == "@everyone")
    # its own row replaces the category's, so reactions are allowed here
    assert not everyone.deny & 64


def _role(data, name):
    return find(data["roles"], name)


def _channel(data, name):
    return find(data["channels"], name)


def _channel_rows(data, name):
    return _channel(data, name).setdefault("overwrites", [])


REFUSALS = {
    "a role holding manage_roles": (
        lambda d: _role(d, "Moderator")["permissions"].append("manage_roles"),
        "manage_roles",
    ),
    "a role holding administrator": (
        lambda d: _role(d, "Moderator")["permissions"].append("administrator"),
        "administrator",
    ),
    "everyone holding a structural permission": (
        lambda d: d["everyone"]["permissions"].append("manage_webhooks"),
        "everyone may not hold",
    ),
    "an overwrite allowing manage_channels": (
        lambda d: _channel_rows(d, "general").append({"target": "@everyone", "allow": ["manage_channels"]}),
        "may not allow",
    ),
    "a text channel granting manage_channels to a staff role": (
        lambda d: _channel_rows(d, "general").append({"target": "Maintainer", "allow": ["manage_channels"]}),
        "may not allow",
    ),
    "a stage granting manage_channels to a member role": (
        lambda d: _channel_rows(d, "Town hall").append({"target": "Contributor", "allow": ["manage_channels"]}),
        "may not allow",
    ),
    "a stage granting manage_roles to a staff role": (
        lambda d: _channel_rows(d, "Town hall").append({"target": "Maintainer", "allow": ["manage_roles"]}),
        "may not allow",
    ),
    "an overwrite denying the bot": (
        lambda d: _channel_rows(d, "general").append({"target": "@bot", "deny": ["view_channel"]}),
        "the bot may not be denied",
    ),
    "an unknown overwrite target": (
        lambda d: _channel_rows(d, "general").append({"target": "Nobody", "allow": ["view_channel"]}),
        "unknown target",
    ),
    "an unknown permission": (lambda d: d["permission_sets"]["member"].append("fly"), "unknown permission"),
    "a wrong schema": (lambda d: d.update(schema=2), "schema"),
    "a bad verification level": (lambda d: d["server"].update(verification_level=9), "verification_level"),
    "a slow mode over the limit": (lambda d: _channel(d, "general").update(slow_mode=99999), "slow_mode"),
    "a channel name with capitals": (lambda d: _channel(d, "general").update(name="Gen Eral"), "lower case words"),
    "a channel in a missing category": (
        lambda d: _channel(d, "general").update(category="Nowhere"),
        "not in the layout",
    ),
    "a topic over 1024 characters": (lambda d: _channel(d, "general").update(topic="x" * 1025), "topic is 1025"),
    "a tag name over 20 characters": (
        lambda d: _channel(d, "help")["forum"]["tags"].append({"name": "a tag name that is far too long"}),
        "tag",
    ),
    "more than 20 tags": (
        lambda d: _channel(d, "help")["forum"].update(tags=[{"name": f"Tag {i}"} for i in range(21)]),
        "at most 20 tags",
    ),
    "a timeout on a spam rule": (
        lambda d: find(d["automod"], "Spam")["actions"].append({"type": "timeout", "seconds": 60}),
        "keyword and mention spam",
    ),
    "a timeout of zero": (
        lambda d: find(d["automod"], "Mention raid")["actions"].__setitem__(2, {"type": "timeout", "seconds": 0}),
        "timeout",
    ),
    "a custom message over 150 characters": (
        lambda d: find(d["automod"], "Invite links")["actions"].__setitem__(0, {"type": "block", "message": "m" * 151}),
        "150 characters",
    ),
    "a keyword over 60 characters": (
        lambda d: find(d["automod"], "Scam phrases")["keywords"].append("k" * 61),
        "60 characters",
    ),
    "eleven patterns": (
        lambda d: find(d["automod"], "Invite links").update(patterns=["a"] * 11),
        "at most 10 patterns",
    ),
    "a second spam rule": (
        lambda d: d["automod"].append({"name": "Spam two", "trigger": "spam", "actions": [{"type": "block"}]}),
        "allows 1 spam",
    ),
    "seven keyword rules": (
        lambda d: d["automod"].extend(
            {"name": f"Words {i}", "trigger": "keyword", "keywords": ["x"], "actions": [{"type": "block"}]}
            for i in range(3)
        ),
        "allows 6 keyword",
    ),
    "a webhook name holding discord": (lambda d: d["webhooks"][0].update(name="Discord relay"), "discord or clyde"),
    "a webhook name holding clyde": (lambda d: d["webhooks"][0].update(name="Clyde relay"), "discord or clyde"),
    "a webhook secret in lower case": (lambda d: d["webhooks"][0].update(secret="lower"), "secret must be"),
    "a webhook for a missing channel": (lambda d: d["webhooks"][0].update(channel="nowhere"), "not in the layout"),
    "a system channel that is not in the layout": (
        lambda d: d["server"].update(system_channel="nowhere"),
        "system_channel",
    ),
    "an exempt role that does not exist": (
        lambda d: find(d["automod"], "Mention raid").update(exempt_roles=["Ghost"]),
        "exempt role",
    ),
    "an alert in a missing channel": (
        lambda d: find(d["automod"], "Spam").update(actions=[{"type": "alert", "channel": "nowhere"}]),
        "alert channel",
    ),
    "too few onboarding defaults": (
        lambda d: d["onboarding"].update(default_channels=d["onboarding"]["default_channels"][:5]),
        "at least 7",
    ),
    "a role listed twice": (lambda d: d["roles"].append(dict(d["roles"][0])), "twice"),
    "a forum setting on a text channel": (
        lambda d: _channel(d, "general").update(forum={"require_tag": True}),
        "only a forum",
    ),
    "a bad auto archive time": (
        lambda d: _channel(d, "help")["forum"].update(auto_archive_minutes=5),
        "auto_archive_minutes",
    ),
    "an option giving nothing": (
        lambda d: d["onboarding"]["prompts"][0]["options"].append({"title": "Nothing", "roles": [], "channels": []}),
        "at least one role or channel",
    ),
}


@pytest.mark.parametrize("label", list(REFUSALS))
def test_check_refuses(tmp_path, label):
    mutate, needle = REFUSALS[label]
    data = layout_data()
    mutate(data)
    problems = errors_of(write_layout(tmp_path, data))
    assert any(needle in p for p in problems), problems


def test_a_layout_with_an_id_or_a_webhook_address_is_refused(tmp_path):
    data = layout_data()
    data["server"]["note"] = "1" * 18
    assert any("17 to 20 digits" in p for p in errors_of(write_layout(tmp_path, data)))
    data = layout_data()
    data["server"]["note"] = "x/api/webhooks/y"
    assert any("webhook" in p for p in errors_of(write_layout(tmp_path, data)))
    data = layout_data()
    data["server"]["note"] = "N" + "a" * 24 + ".abcdef." + "b" * 27
    assert any("token" in p for p in errors_of(write_layout(tmp_path, data)))


def test_onboarding_needs_five_channels_everyone_can_post_in(tmp_path):
    data = layout_data()
    postable = [n for n in data["onboarding"]["default_channels"] if _channel(data, n)["type"] in ("text", "forum")]
    # make every text channel read only so that fewer than five accept posts
    for name in postable:
        if _channel(data, name)["type"] == "text":
            rows = _channel_rows(data, name)
            rows[:] = [r for r in rows if r["target"] != "@everyone"] + [
                {"target": "@everyone", "deny": ["send_messages"]}
            ]
    problems = errors_of(write_layout(tmp_path, data))
    assert any("at least 5" in p for p in problems), problems


def test_a_disabled_channel_cannot_be_an_onboarding_default(tmp_path):
    data = layout_data()
    disabled = holding_back(data)["name"]
    data["onboarding"]["default_channels"].append(disabled)
    assert any(disabled in p for p in errors_of(write_layout(tmp_path, data)))


def test_a_message_file_over_the_limit_is_refused(tmp_path):
    base = tmp_path / "discord"
    (base / "layout").mkdir(parents=True)
    shutil.copytree(ROOT / "texts", base / "texts")
    (base / "texts" / "long.md").write_text("x" * 2001)
    data = layout_data()
    data["channels"][0]["messages"] = ["texts/long.md"]
    path = base / "layout" / "v.toml"
    path.write_text(dump(data))
    assert any("2001 characters" in p for p in errors_of(path, base))


def test_a_missing_text_file_is_reported(tmp_path):
    data = layout_data()
    data["channels"][0]["messages"] = ["texts/absent.md"]
    assert any("absent.md" in p for p in errors_of(write_layout(tmp_path, data)))


@pytest.mark.parametrize(
    "text, what",
    [
        ("one \u2014 two", "dash"),
        ("one \u2013 two", "dash"),
        ("red, and blue", "comma"),
        ("red,\nor blue", "comma"),
        ("hello \U0001f600", "emoji"),
        ("tick \u2705", "emoji"),
    ],
)
def test_style_rules_catch_long_dashes_commas_and_emoji(tmp_path, text, what):
    data = layout_data()
    _channel(data, "general")["topic"] = text
    assert style_errors(load(write_layout(tmp_path, data), base_dir=ROOT)), what


def test_style_rules_let_ordinary_text_through():
    assert style_problems("Ask in help, then in hardware. Red and blue. Wait or not. A hyphen-ated word.") == []


def test_check_command_succeeds_and_fails(server, tmp_path):
    ok = server.run("check")
    assert ok.code == 0 and "is valid" in ok.out
    data = layout_data()
    data["schema"] = 2
    bad = server.run("check", layout=write_layout(tmp_path, data))
    assert bad.code == 2 and "schema" in bad.err


def test_find_layout_uses_the_only_file_in_layout_or_asks(tmp_path):
    with pytest.raises(cli.SetupError):
        cli.find_layout(None, tmp_path)
    assert cli.find_layout(None, ROOT).name.endswith(".toml")


def test_hash_changes_with_the_file(tmp_path):
    a = load(layout_path())
    data = layout_data()
    data["server"]["description"] += " More."
    b = load(write_layout(tmp_path, data), base_dir=ROOT)
    assert a.hash8 != b.hash8 and re.fullmatch(r"[0-9a-f]{8}", a.hash8)
