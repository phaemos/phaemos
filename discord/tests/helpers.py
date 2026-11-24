"""Small helpers shared by the tests. Layouts are changed as data, never by editing their text, so
the same tests hold for every project's layout."""

from __future__ import annotations

import copy
import json
import re
import tomllib
from pathlib import Path

from conftest import ROOT, layout_path

from serverkit.layout import LayoutError, load


def layout_data() -> dict:
    return copy.deepcopy(tomllib.loads(layout_path().read_text(encoding="utf-8")))


def holding_back(data: dict, name: str = "private-help", note: str = "50 members") -> dict:
    """The project layouts hold nothing back, so a test of the deferral feature makes its own waiting channel."""
    channel = next(c for c in data["channels"] if c["name"] == name)
    channel.update({"enabled": False, "threshold": note, "threshold_members": 50})
    return channel


def _key(name: str) -> str:
    return name if re.fullmatch(r"[A-Za-z0-9_-]+", name) else json.dumps(name)


def _value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    raise TypeError(type(value))


def _is_aot(value) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(v, dict) for v in value)


def _emit(table: dict, path: list[str], lines: list[str]) -> None:
    for key, value in table.items():
        if not isinstance(value, dict) and not _is_aot(value):
            lines.append(f"{_key(key)} = {_value(value)}")
    for key, value in table.items():
        here = [*path, _key(key)]
        if isinstance(value, dict):
            lines.append("")
            lines.append(f"[{'.'.join(here)}]")
            _emit(value, here, lines)
        elif _is_aot(value):
            for item in value:
                lines.append("")
                lines.append(f"[[{'.'.join(here)}]]")
                _emit(item, here, lines)


def dump(data: dict) -> str:
    lines: list[str] = []
    _emit(data, [], lines)
    return "\n".join(lines) + "\n"


def write_layout(tmp_path: Path, data: dict, name: str = "variant.toml") -> Path:
    path = tmp_path / "layout" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text(dump(data), encoding="utf-8")
    # the texts and the command content sit beside the layout, as they do in the real folder
    for folder in ("texts", "content", "assets"):
        link = tmp_path / folder
        if not link.exists():
            link.symlink_to(ROOT / folder)
    return path


def errors_of(path: Path, base_dir: Path = ROOT) -> list[str]:
    try:
        load(path, base_dir=base_dir)
    except LayoutError as exc:
        return exc.errors
    return []


def find(items: list[dict], name: str) -> dict:
    return next(i for i in items if i["name"] == name)


def raw(fake, method: str, path: str, body=None, *, token: str | None = None, headers: dict | None = None):
    """A request straight to the fake, to show what it refuses. Returns (status, decoded body)."""
    import urllib.error
    import urllib.request

    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(fake.url + path, data=data, method=method)
    request.add_header("Authorization", f"Bot {token or fake.token}")
    request.add_header("User-Agent", "DiscordBot (https://example.org/repo, 1.0)")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        if value is None:
            request.remove_header(key)
        else:
            request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = response.read()
            return response.status, json.loads(payload) if payload else None
    except urllib.error.HTTPError as err:
        payload = err.read()
        return err.code, json.loads(payload) if payload else None


def target_id(fake, target: str) -> str:
    if target == "@everyone":
        return fake.guild_id
    if target == "@bot":
        return fake.bot_role_id
    return fake.role_named(target)["id"]


def expected_rows(fake, overwrites) -> dict[str, tuple[int, int]]:
    return {target_id(fake, o.target): (o.allow, o.deny) for o in overwrites}


def actual_rows(channel: dict) -> dict[str, tuple[int, int]]:
    return {o["id"]: (int(o["allow"]), int(o["deny"])) for o in channel["permission_overwrites"]}


def writes(fake) -> list[tuple[str, str, int]]:
    return [r for r in fake.requests if r[0] != "GET" and r[2] < 400]


def deletes(fake) -> list[str]:
    """The reasons of every delete the script made, apart from removing the notice a pin leaves behind."""
    return [
        a["reason"] for a in fake.audit if a["method"] == "DELETE" and not a["reason"].endswith("remove the pin notice")
    ]


def methods(fake) -> set[str]:
    return {m for m, _p, s in fake.requests if m != "GET" and s < 400}


def only_words(text: str, *wanted: str) -> list[tuple[str, str]]:
    from conftest import words

    return [w for w in words(text) if w[0] in wanted]
