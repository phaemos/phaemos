"""Style rules for every piece of text a member can read."""

from __future__ import annotations

import re

DASHES = ("—", "–")
COMMA_BEFORE_CONJUNCTION = re.compile(r",\s+(?:and|or)\b", re.IGNORECASE)
EMOJI = re.compile("[" "←-⇿" "⌀-⏿" "①-⓿" "■-➿" "⤀-⥿" "⬀-⯿" "〰〽㊗㊙" "️‍" "\U0001f000-\U0001faff" "]")
# a run of 17 to 20 digits is the shape of a Discord id
ID_SHAPE = re.compile(r"(?<!\d)\d{17,20}(?!\d)")
WEBHOOK_SHAPE = re.compile(r"/api/(?:v\d+/)?webhooks/\d+", re.IGNORECASE)
TOKEN_SHAPE = re.compile(r"[MNO][A-Za-z\d_-]{23,25}\.[A-Za-z\d_-]{6}\.[A-Za-z\d_-]{27,}")


def style_problems(text: str) -> list[str]:
    problems = []
    if any(dash in text for dash in DASHES):
        problems.append("holds a long dash")
    if COMMA_BEFORE_CONJUNCTION.search(text):
        problems.append('has a comma before "and" or "or"')
    if EMOJI.search(text):
        problems.append("holds an emoji or a decorative symbol")
    return problems


def identifier_problems(text: str) -> list[str]:
    problems = []
    if ID_SHAPE.search(text):
        problems.append("holds a run of 17 to 20 digits")
    if WEBHOOK_SHAPE.search(text):
        problems.append("holds a webhook address")
    if TOKEN_SHAPE.search(text):
        problems.append("holds something shaped like a token")
    return problems
