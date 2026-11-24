from __future__ import annotations

import io
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from fake_discord import FakeClock, FakeDiscord  # noqa: E402

from serverkit import cli  # noqa: E402
from serverkit.layout import load  # noqa: E402


def layout_path() -> Path:
    found = sorted((ROOT / "layout").glob("*.toml"))
    assert len(found) == 1, "each copy of this folder holds exactly one layout"
    return found[0]


@dataclass
class Outcome:
    code: int
    out: str
    err: str
    stored: list[tuple[list[str], str]] = field(default_factory=list)


class Harness:
    def __init__(self, fake: FakeDiscord, path: Path):
        self.fake = fake
        self.path = path

    def run(
        self,
        *argv: str,
        stdin: str = "",
        tty: bool = False,
        env: dict | None = None,
        layout: Path | None = None,
        now=None,
    ) -> Outcome:
        out, err = io.StringIO(), io.StringIO()
        stored: list[tuple[list[str], str]] = []
        base_env = {
            "DISCORD_BOT_TOKEN": self.fake.token,
            "DISCORD_API_BASE": self.fake.url,
            "NO_COLOR": "1",
        }
        base_env.update(env or {})
        base_env = {k: v for k, v in base_env.items() if v is not None}
        args = list(argv)
        if "--layout" not in args:
            args += ["--layout", str(layout or self.path)]
        kwargs = {}
        if now:
            kwargs["now"] = now
        code = cli.main(
            args,
            env=base_env,
            stdin=io.StringIO(stdin),
            stdout=out,
            stderr=err,
            isatty=lambda: tty,
            sleep=self.fake.clock.sleep,
            clock=self.fake.clock.now,
            runner=lambda command, value: stored.append((command, value)),
            cwd=ROOT,
            **kwargs,
        )
        return Outcome(code, out.getvalue(), err.getvalue(), stored)

    def owner_roles(self, layout_file: Path | None = None) -> None:
        """The owner's hand work: make or correct the roles the layout marks as the owner's, above the bot's."""
        wanted = load(layout_file or self.path)
        fake = self.fake
        for role in reversed([r for r in wanted.roles if r.owner]):
            held = next((r for r in fake.roles.values() if r["name"] == role.name and not r["managed"]), None)
            if held is None:
                held = fake.add_role(role.name, role.permissions)
            held["permissions"] = str(role.permissions)
            held["hoist"] = role.hoist
        names = {w.name for w in wanted.roles if w.owner}
        # the owner drags the bot's role below theirs and above everything else, the order of the rest unchanged
        rest = sorted(
            (r for r in fake.roles.values() if r["id"] != fake.guild_id), key=lambda r: r["position"], reverse=True
        )
        owners = [r for r in rest if r["name"] in names]
        others = [r for r in rest if r["name"] not in names and r["id"] != fake.bot_role_id]
        order = [*owners, fake.roles[fake.bot_role_id], *others]
        for place, role in zip(range(len(order), 0, -1), order, strict=True):
            role["position"] = place

    def apply(self, *flags: str, **kwargs) -> Outcome:
        return self.run("apply", *flags, **kwargs)

    def plan(self, *flags: str, **kwargs) -> Outcome:
        return self.run("plan", *flags, **kwargs)


@pytest.fixture
def layout():
    return load(layout_path())


@pytest.fixture
def make_server(layout):
    created: list[FakeDiscord] = []

    def factory(
        community: bool = True,
        bot_permissions: int | None = None,
        name: str | None = None,
        owner_roles: bool = True,
        **switches,
    ) -> Harness:
        fake = FakeDiscord(
            guild_name=name or layout.name,
            bot_permissions=layout.bot_permissions() if bot_permissions is None else bot_permissions,
            clock=FakeClock(),
        )
        for key, value in switches.items():
            setattr(fake, key, value)
        fake.start()
        created.append(fake)
        if community:
            fake.make_community(wizard_channels=False)
        harness = Harness(fake, layout_path())
        if owner_roles:
            harness.owner_roles()
        return harness

    yield factory
    for fake in created:
        fake.stop()


@pytest.fixture
def server(make_server):
    return make_server()


def words(text: str) -> list[tuple[str, str]]:
    """The plan lines as (word, text) pairs."""
    pairs = []
    for line in text.splitlines():
        match = re.match(r"^  (\w+)\s+(.*)$", line)
        if match:
            pairs.append((match.group(1), match.group(2)))
    return pairs
