"""How the texts in texts/ become Discord messages: links by id, headings and the embed split."""

from __future__ import annotations

import re
from collections.abc import Callable

REF = re.compile(r"\{(channel|role|command):([^}]+)\}")
HEADING = re.compile(r"^#{1,3} (.*)$", re.MULTILINE)
# a snowflake is at most 20 digits. These are the widest a link can be once the id is filled in
CHANNEL_LINK = 2 + 20 + 1
ROLE_LINK = 3 + 20 + 1
NAV_LINK = len("<id:customize>")


def refs(text: str) -> list[tuple[str, str]]:
    return REF.findall(text)


def split_embed(text: str) -> tuple[str, str]:
    """The first line is the title and the rest is the description."""
    first, _, rest = text.partition("\n")
    return first.strip(), rest.strip("\n")


def plain_markdown(text: str) -> str:
    """Headings written as ### in the files become bold lines in a plain message."""
    return HEADING.sub(lambda m: f"**{m.group(1)}**", text)


def render(text: str, resolve: Callable[[str, str], str], contact: str = "") -> str:
    text = REF.sub(lambda m: resolve(m.group(1), m.group(2)), text)
    return text.replace("{contact_email}", contact).replace("{nav:customize}", "<id:customize>")


def widest(text: str, contact: str = "") -> int:
    """The longest the text can be once every link carries a full length id."""

    def wide(kind: str, name: str) -> str:
        if kind == "channel":
            return "x" * CHANNEL_LINK
        if kind == "role":
            return "x" * ROLE_LINK
        return "x" * (len(name.split(" ")[0]) + 1 + 20 + 3 + len(name.partition(" ")[2]))

    return len(render(text, wide, contact))
