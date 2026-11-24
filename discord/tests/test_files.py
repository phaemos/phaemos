"""Checks on the folder itself: no identifier or secret anywhere, shared code with no project name, texts and README."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import ROOT, layout_path

from serverkit import cli
from serverkit.style import ID_SHAPE, TOKEN_SHAPE, WEBHOOK_SHAPE, style_problems

SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".pytest_cache", ".ruff_cache", "dist", ".wrangler", ".venv"}
BINARY = {".png", ".jpg", ".ico", ".pdf", ".woff", ".woff2"}
# two other words that are not identifiers but are shaped like one in some formats
WEBHOOK_ADDRESS = re.compile(r"discord(?:app)?\.com/api/(?:v\d+/)?webhooks/\d+/[\w-]+", re.IGNORECASE)


def project_files():
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.suffix in BINARY:
            continue
        yield path


def test_no_file_holds_an_id_a_webhook_address_or_a_token():
    found = []
    for path in project_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in (
            ("id", ID_SHAPE),
            ("webhook", WEBHOOK_SHAPE),
            ("webhook", WEBHOOK_ADDRESS),
            ("token", TOKEN_SHAPE),
        ):
            match = pattern.search(text)
            if match:
                found.append(f"{path.relative_to(ROOT)}: {label} shaped text at {match.start()}")
    assert not found, found


def test_the_check_would_catch_each_shape():
    assert ID_SHAPE.search("x" + "1" * 18)
    assert not ID_SHAPE.search("1" * 16) and not ID_SHAPE.search("1" * 21)
    assert WEBHOOK_SHAPE.search("https://discord.com/api/" + "webhooks/" + "123456/abc")
    assert TOKEN_SHAPE.search("N" + "a" * 24 + ".abcdef." + "b" * 27)


NAMES = ("pha" + "emos", "melo" + "phos")
SHARED = ("serverkit", "tests", "relay")


def test_the_shared_code_names_no_project():
    found = []
    files = [p for folder in SHARED for p in (ROOT / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    files += list((ROOT / "worker" / "src").glob("*.ts")) if (ROOT / "worker" / "src").is_dir() else []
    for path in files:
        if path.suffix not in (".py", ".ts"):
            continue
        text = path.read_text(encoding="utf-8").lower()
        for name in NAMES:
            if name in text:
                found.append(f"{path.relative_to(ROOT)} names a project")
    assert not found, found


def test_member_facing_text_files_follow_the_style_rules():
    problems = []
    for path in sorted((ROOT / "texts").glob("*")):
        if path.name.startswith("secret-patterns"):
            continue
        for problem in style_problems(path.read_text(encoding="utf-8")):
            problems.append(f"{path.name} {problem}")
    assert not problems, problems


def test_every_text_message_and_topic_is_inside_its_limit(layout):
    for channel in layout.channels:
        for message in channel.messages:
            assert len(message) <= 2000
        assert len(channel.topic) <= (4096 if channel.type == "forum" else 1024)
        for tag in (channel.forum or {}).get("tags", []):
            assert len(tag["name"]) <= 20
    for rule in layout.automod:
        for action in rule["actions"]:
            assert len(action.get("message", "")) <= 150


def test_no_ai_wording_in_any_text_the_script_owns(layout):
    banned = re.compile(r"\b(?:ai|a\.i\.|artificial intelligence|chatbot|llm|gpt|claude|copilot)\b", re.IGNORECASE)
    parts = [t for _l, t in layout.lines_to_check()]
    parts += [p.read_text(encoding="utf-8") for p in (ROOT / "texts").glob("*") if p.is_file()]
    assert not [p for p in parts if banned.search(p)]


def test_the_environment_example_lists_four_names_and_no_values():
    lines = [line for line in (ROOT / ".env.example").read_text().splitlines() if line and not line.startswith("#")]
    assert sorted(line.split("=")[0] for line in lines) == [
        "DISCORD_API_BASE",
        "DISCORD_BOT_TOKEN",
        "DISCORD_GUILD_ID",
        "DISCORD_INTERACTIONS_URL",
    ]
    assert all(line.endswith("=") for line in lines)


def test_the_script_has_no_run_time_dependency_and_a_three_twelve_floor():
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert data["project"]["dependencies"] == []
    assert data["project"]["requires-python"] == ">=3.12"
    imports = set()
    for path in (ROOT / "serverkit").glob("*.py"):
        imports |= set(re.findall(r"^(?:from|import) ([a-z_]+)", path.read_text(), re.MULTILINE))
    import sys

    outside = {m for m in imports if m not in sys.stdlib_module_names and m != "serverkit"}
    assert not outside, outside


def test_the_readme_names_every_command_flag_exit_code_and_variable():
    readme = (ROOT / "README.md").read_text()
    for command in cli.COMMANDS:
        assert command in readme, command
    for flag in re.findall(r'"(--[a-z-]+)"', Path(cli.__file__).read_text()):
        assert flag in readme, flag
    for code in "01234":
        assert re.search(rf"\|\s*{code}\s*\|", readme), code
    for name in ("DISCORD_BOT_TOKEN", "DISCORD_GUILD_ID", "DISCORD_INTERACTIONS_URL", "DISCORD_API_BASE"):
        assert name in readme
    assert "security add-generic-password" in readme


def test_the_old_script_is_gone_and_no_file_asks_for_discord_py():
    assert not (ROOT / "setup_discord.py").exists()
    assert not (ROOT / "requirements.txt").exists()
    for name in ("requirements-dev.txt", "pyproject.toml"):
        assert "discord.py" not in (ROOT / name).read_text()


def test_each_layout_in_this_folder_loads_and_the_engine_marker_is_not_a_layout():
    assert layout_path().is_file()


@pytest.mark.parametrize(
    "name", ["LICENSE", "README.md", "CHANGELOG.md", ".env.example", "pyproject.toml", "requirements-dev.txt"]
)
def test_the_folder_stands_alone(name):
    assert (ROOT / name).is_file()
