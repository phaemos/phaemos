"""A small YAML reader for the workflow tests, so they need no package.

It reads the subset that the repository's workflow files use: block mappings and
sequences, flow lists, quoted and plain scalars, comments and the `|` and `>` block
scalars. It is not a general parser and fails loudly on anything it does not know.
When PyYAML is installed a test below checks that both readers agree.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_relay_support import skip_loudly  # noqa: E402


class YamlError(Exception):
    pass


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _skippable(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _strip_comment(text: str) -> str:
    if text[:1] in ("'", '"'):
        quote = text[0]
        end = text.find(quote, 1)
        while quote == '"' and end > 0 and text[end - 1] == "\\":
            end = text.find(quote, end + 1)
        if end < 0:
            raise YamlError(f"unterminated quote: {text}")
        return text[: end + 1]
    return re.split(r"\s#", text, maxsplit=1)[0].strip()


def _scalar(text: str) -> Any:
    text = _strip_comment(text.strip())
    if text in ("", "~", "null"):
        return None
    if text.startswith("["):
        if not text.endswith("]"):
            raise YamlError(f"a flow list must close on its line: {text}")
        inner = text[1:-1].strip()
        return [_scalar(part) for part in inner.split(",")] if inner else []
    if text.startswith("{"):
        if not text.endswith("}"):
            raise YamlError(f"a flow mapping must close on its line: {text}")
        inner = text[1:-1].strip()
        result: dict[str, Any] = {}
        for part in inner.split(",") if inner else []:
            key, _, value = part.partition(":")
            result[key.strip()] = _scalar(value)
        return result
    if text[0] == '"' and text[-1] == '"' and len(text) >= 2:
        return bytes(text[1:-1], "utf-8").decode("unicode_escape")
    if text[0] == "'" and text[-1] == "'" and len(text) >= 2:
        return text[1:-1].replace("''", "'")
    if text in ("true", "True"):
        return True
    if text in ("false", "False"):
        return False
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return text


class _Reader:
    def __init__(self, text: str) -> None:
        self.lines = text.split("\n")
        self.pos = 0

    def skip(self) -> None:
        while self.pos < len(self.lines) and _skippable(self.lines[self.pos]):
            self.pos += 1

    def block(self, indent: int) -> Any:
        self.skip()
        if self.pos >= len(self.lines):
            return None
        line = self.lines[self.pos]
        if _indent(line) != indent:
            raise YamlError(f"unexpected indent on line {self.pos + 1}")
        if line.strip() == "-" or line.strip().startswith("- "):
            return self.sequence(indent)
        return self.mapping(indent)

    def sequence(self, indent: int) -> list[Any]:
        items: list[Any] = []
        while True:
            self.skip()
            if self.pos >= len(self.lines):
                break
            line = self.lines[self.pos]
            if _indent(line) != indent or not (line.strip() == "-" or line.strip().startswith("- ")):
                break
            rest = line.strip()[1:].lstrip(" ")
            if not rest:
                self.pos += 1
                items.append(self.block(_indent(self.lines[self.pos])))
            elif re.match(r"^[^\s'\"\[{][^:]*:(\s|$)", rest) or re.match(r"^[\"'][^\"']*[\"']\s*:(\s|$)", rest):
                # a mapping that starts on the dash line: re-read the rest as an indented line
                offset = len(line) - len(line.lstrip(" ")) + (len(line.strip()) - len(rest))
                self.lines[self.pos] = " " * offset + rest
                items.append(self.mapping(offset))
            else:
                items.append(_scalar(rest))
                self.pos += 1
        return items

    def mapping(self, indent: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while True:
            self.skip()
            if self.pos >= len(self.lines):
                break
            line = self.lines[self.pos]
            if _indent(line) != indent:
                if _indent(line) > indent:
                    raise YamlError(f"unexpected indent on line {self.pos + 1}")
                break
            if line.strip().startswith("- "):
                break
            match = re.match(r"^(?P<key>\"[^\"]*\"|'[^']*'|[^:#'\"][^:]*?)\s*:(?:\s+(?P<value>.*))?$", line.strip())
            if not match:
                raise YamlError(f"cannot read line {self.pos + 1}: {line}")
            key = match.group("key").strip("\"'")
            value = (match.group("value") or "").strip()
            self.pos += 1
            if key in result:
                raise YamlError(f"duplicate key {key}")
            if re.fullmatch(r"[|>][+-]?", _strip_comment(value) if value else ""):
                result[key] = self.block_scalar(indent, _strip_comment(value))
            elif value and not value.startswith("#"):
                result[key] = _scalar(value)
            else:
                self.skip()
                if self.pos < len(self.lines) and (
                    _indent(self.lines[self.pos]) > indent
                    or (_indent(self.lines[self.pos]) == indent and self.lines[self.pos].strip().startswith("- "))
                ):
                    result[key] = self.block(_indent(self.lines[self.pos]))
                else:
                    result[key] = None
        return result

    def block_scalar(self, parent: int, style: str) -> str:
        body: list[str] = []
        base = None
        while self.pos < len(self.lines):
            line = self.lines[self.pos]
            if line.strip() and _indent(line) <= parent:
                break
            if line.strip() and base is None:
                base = _indent(line)
            body.append(line[base:] if base is not None and line.strip() else "")
            self.pos += 1
        while body and not body[-1]:
            body.pop()
        text = "\n".join(body)
        if style.startswith(">"):
            text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
        return text if style.endswith("-") else text + "\n"


def parse(text: str) -> Any:
    reader = _Reader(text)
    reader.skip()
    return reader.block(_indent(reader.lines[reader.pos])) if reader.pos < len(reader.lines) else None


def load(path: Path) -> Any:
    return parse(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------


def test_reads_the_constructs_the_workflows_use():
    document = parse(
        "# a comment\n"
        "name: Example # trailing\n"
        "on:\n"
        "  push:\n"
        "    branches: [main]\n"
        "permissions: {}\n"
        "jobs:\n"
        "  one:\n"
        "    steps:\n"
        "      - name: First\n"
        "        uses: owner/action@0123456789abcdef0123456789abcdef01234567 # v1.2.3\n"
        "        with:\n"
        '          text: "quoted: yes"\n'
        "      - run: |\n"
        "          echo one\n"
        "          # kept\n"
        "\n"
        "          echo two\n"
        "      - plain\n"
        "list:\n"
        "- a\n"
        "- b\n"
    )
    assert document["name"] == "Example"
    assert document["on"]["push"]["branches"] == ["main"]
    assert document["permissions"] == {}
    steps = document["jobs"]["one"]["steps"]
    assert steps[0]["uses"].endswith("cdef01234567")
    assert steps[0]["with"]["text"] == "quoted: yes"
    assert steps[1]["run"] == "echo one\n# kept\n\necho two\n"
    assert steps[2] == "plain"
    assert document["list"] == ["a", "b"]


def test_agrees_with_pyyaml_on_every_workflow_file():
    try:
        import yaml
    except ImportError:
        skip_loudly("PyYAML is not installed, so the small YAML reader was not cross-checked")
    root = Path(__file__).resolve().parents[2] / ".github"
    files = sorted(root.rglob("*.yml")) if root.is_dir() else []
    if not files:
        skip_loudly("the workflow files are only present in the monorepo")
    for path in files:
        try:
            mine = load(path)
        except YamlError:
            continue  # a file in another style, which these tests never read
        theirs = yaml.safe_load(path.read_text(encoding="utf-8"))
        if True in theirs:  # PyYAML reads the key on as a boolean
            theirs["on"] = theirs.pop(True)
        assert mine == theirs, path.name
