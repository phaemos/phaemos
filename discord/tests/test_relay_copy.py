"""Checks that hold in the monorepo and in the published copy of this folder alike.

Everything about the script runs in both places. Only the workflow checks need the
monorepo and those live in test_relay_workflow.py, which says so when it skips.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_relay_support import ROOT, relay  # noqa: E402


def test_no_workflow_file_sits_inside_discord_where_the_split_would_publish_it():
    skipped = {"node_modules", "__pycache__", ".git"}
    for path in ROOT.rglob("*"):
        if skipped & set(path.parts):
            continue
        if path.is_dir() and path.name in (".github", "workflows"):
            pytest.fail(f"{path} would be published to the root of the copy")
        if (
            path.is_file()
            and path.suffix in (".yml", ".yaml")
            and ("workflows" in path.parts or ".github" in path.parts)
        ):
            pytest.fail(f"{path} would run in the published copy")


def test_the_poster_loads_from_this_folder_alone():
    assert (ROOT / "relay" / "post.py").is_file()
    assert callable(relay.main)
