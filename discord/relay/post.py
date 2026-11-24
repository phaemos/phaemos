#!/usr/bin/env python3
"""Posts GitHub activity to Discord webhooks. Standard library only.

One run handles one GitHub event. The event is read from the file that
GITHUB_EVENT_PATH names, so no title or body ever passes through a shell line or a
workflow expression. Routing, labels and colours come from the [relay] table of the
project's layout file, so this file holds no project name.

Exit codes: 0 posted, skipped or nothing to do. 1 a post failed. 2 a configuration
problem (layout, event file or webhook address).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import http.client
import json
import os
import re
import sys
import time
import tomllib
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

# discord limits [D-HOOK] [D-MSG]. the description is cut earlier than its limit of
# 4,096 so the closing link and a closed code block always fit.
CONTENT_LIMIT = 2000
EMBED_TITLE_LIMIT = 256
EMBED_DESCRIPTION_LIMIT = 3800
EMBED_FIELD_VALUE_LIMIT = 1024
EMBED_FOOTER_LIMIT = 2048
EMBED_TOTAL_LIMIT = 6000
USERNAME_LIMIT = 80
FEED_TITLE_LIMIT = 200
MAX_PUSH_LINES = 5
FEED_FLAGS = 4096  # suppress notifications
NO_MENTIONS = {"parse": []}

# delivery: three more tries after these waits, a 10 second timeout on each request
# and one budget for the whole run that sits inside the job's own 3 minute limit.
RETRY_DELAYS = (2, 8, 30)
REQUEST_TIMEOUT = 10
MAX_RATE_LIMIT_WAIT = 60
MAX_RATE_LIMIT_WAITS = 5
RUN_BUDGET = 150

# the address prefix is written in two pieces so that the repository's scan for
# webhook addresses does not match this file.
HOOK_PATH_PREFIX = "/api/" + "webhooks/"
HOOK_HOSTS = ("discord.com", "discordapp.com")
LOOPBACK_HOSTS = ("127.0.0.1", "localhost")

MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
CALLOUTS = {
    "NOTE": "Note",
    "TIP": "Tip",
    "IMPORTANT": "Important",
    "WARNING": "Warning",
    "CAUTION": "Caution",
}
INVITE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:discord(?:app)?\.com/invite/|discord\.gg/|discord\.me/|dsc\.gg/)\S*",
    re.IGNORECASE,
)
# built from code points so that no invisible character sits in the source
ZWSP = chr(0x200B)
LQUOTE = chr(0x2039)
RQUOTE = chr(0x203A)
# a post about something a stranger wrote waits until a maintainer has acted on it. These are
# the author associations GitHub gives people with standing in the repository.
TRUSTED = ("OWNER", "MEMBER", "COLLABORATOR")
# the second line of defence: at most this many feed posts in any hour, whatever the source
GOOD_FIRST_ISSUE = "good first issue"
THREAD_NAME_LIMIT = 100
FEED_CAP_PER_HOUR = 10
CAP_WINDOW_SECONDS = 3600
MAX_RUNS_COUNTED = 50  # more runs than this in the window means the cap is reached
COUNT_DEADLINE = 60  # seconds for the whole count, inside the job's 3 minutes
MAX_COUNT_CALLS = 120
WRITE_PERMISSIONS = ("admin", "write")  # GitHub maps the maintain role to write
LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
POSTED_RE = re.compile(r"relay-posted [0-9a-f]{16} .*? to ([A-Z][A-Z0-9_]+) with status")
NOTICE_MARKER = "relay-held-notice"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MARKER_RE = re.compile(r"relay-posted ([0-9a-f]{16})")
SECRET_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


class ConfigError(Exception):
    """The layout, the event or a webhook address is not usable."""


@dataclass
class Config:
    repository: str
    project: str
    colour: int
    commit_types: list[str]
    skip_labels: list[str]
    labels: list[str]
    link_hosts: list[str]
    discussions: dict[str, dict[str, str]]
    webhooks: list[dict[str, str]]

    def webhook_for_channel(self, channel: str) -> tuple[str, str] | None:
        for hook in self.webhooks:
            if hook["channel"] == channel:
                return hook["secret"], hook["name"]
        return None

    def webhook_for_name(self, name: str) -> tuple[str, str] | None:
        for hook in self.webhooks:
            if hook["name"] == name:
                return hook["secret"], hook["name"]
        return None


@dataclass
class Post:
    key: str  # identity of the thing posted, used to avoid a double post on a re-run
    label: str  # fixed words and numbers only, safe to print
    webhook_var: str  # name of the Actions secret that holds the webhook address, never the address itself
    payload: dict[str, Any]
    capped: bool = False  # counts towards the hourly cap on the feed channel
    tag_var: str = ""  # name of the Actions secret that holds a forum tag id, for a post to a forum that requires one


@dataclass
class Result:
    posts: list[Post] = field(default_factory=list)
    skip: str = ""
    error: str = ""  # something that could not be checked, which fails the run so it can be re-run


def load_config(path: str) -> Config:
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"the layout file could not be read ({type(error).__name__})") from error
    relay = data.get("relay")
    if not isinstance(relay, dict):
        raise ConfigError("the layout has no [relay] table")

    def text(name: str) -> str:
        value = relay.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"[relay] needs a text value for {name}")
        return value

    def texts(name: str, default: list[str] | None = None) -> list[str]:
        value = relay.get(name, default)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ConfigError(f"[relay] needs a list of text for {name}")
        return list(value)

    repository = text("repository")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ConfigError("[relay] repository must look like owner/name")
    colour = relay.get("colour")
    if not isinstance(colour, int) or isinstance(colour, bool) or not 0 <= colour <= 0xFFFFFF:
        raise ConfigError("[relay] colour must be a whole number from 0 to 16777215")
    webhooks = []
    for hook in data.get("webhooks", []):
        if not isinstance(hook, dict):
            continue
        name, channel, secret = hook.get("name"), hook.get("channel"), hook.get("secret")
        if not all(isinstance(item, str) for item in (name, channel, secret)):
            continue
        if hook.get("store") != "github":
            continue
        if not SECRET_NAME_RE.match(secret):
            raise ConfigError("a webhook secret name is not in capitals with underscores")
        webhooks.append({"name": name, "channel": channel, "secret": secret})
    discussions = relay.get("discussions", {})
    if not isinstance(discussions, dict):
        raise ConfigError("[relay.discussions] must be a table")
    routes = {}
    for slug, route in discussions.items():
        if isinstance(route, dict) and isinstance(route.get("webhook"), str):
            routes[slug] = {key: str(value) for key, value in route.items()}
    return Config(
        repository=repository,
        project=text("project"),
        colour=colour,
        commit_types=texts("commit_types", ["feat", "fix", "perf", "docs", "revert"]),
        skip_labels=[item.lower() for item in texts("skip_labels", ["automated"])],
        labels=texts("labels", []),
        link_hosts=[item.lower() for item in texts("link_hosts", [])],
        discussions=routes,
        webhooks=webhooks,
    )


# ---------------------------------------------------------------------------------
# text preparation


def clean(text: Any) -> str:
    """Normalises line endings and drops control, format and private characters.

    The format category holds the right-to-left override and the zero width
    characters, which a stranger could use to disguise a title.
    """
    if not isinstance(text, str):
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    out = []
    for char in text:
        category = unicodedata.category(char)
        if char == "\n" or category in ("Zl", "Zp"):
            out.append("\n")
        elif category in ("Cc", "Cf", "Cs", "Co", "Cn"):
            continue
        else:
            out.append(char)
    return "".join(out)


def host_of(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def host_allowed(host: str, cfg: Config) -> bool:
    allowed = ["github.com", *cfg.link_hosts]
    return any(host == item or host.endswith("." + item) for item in allowed)


def escape_inline(text: str) -> str:
    """Makes a stranger's text inert in a one line message."""
    text = text.replace("<", LQUOTE).replace(">", RQUOTE)
    text = re.sub(r"([\\*_~`|\[\]])", r"\\\1", text)
    return text.replace("@", "@" + ZWSP)


def remove_links(text: str) -> str:
    text = INVITE_RE.sub("[link removed]", text)
    return re.sub(r"(?:https?://|www\.)\S+", "[link removed]", text, flags=re.IGNORECASE)


def single_line(text: Any) -> str:
    text = re.sub(r"\s+", " ", clean(text)).strip()
    return remove_links(text)


def cut_raw(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 0)].rstrip() + "..."


def plain(text: Any, limit: int) -> str:
    """A title or subject for a one line post, cut before it is escaped."""
    return escape_inline(cut_raw(single_line(text), limit))


def fit_title(text: Any, limit: int) -> str:
    """A title whose escaped form is within a limit that counts escapes too."""
    raw = single_line(text)
    size = limit
    while True:
        out = escape_inline(cut_raw(raw, size))
        if len(out) <= limit or size <= 3:
            return out[:limit]
        size -= max(1, len(out) - limit)


# fenced code is found line by line, as GitHub does, so an opening fence with no
# closing one runs to the end of the text.
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def split_fences(text: str) -> list[tuple[bool, str]]:
    segments: list[tuple[bool, str]] = []
    buffer: list[str] = []
    marker: tuple[str, int] | None = None
    for line in text.split("\n"):
        match = FENCE_RE.match(line)
        if marker is None:
            if match:
                if buffer:
                    segments.append((False, "\n".join(buffer)))
                buffer = [line]
                marker = (match.group(1)[0], len(match.group(1)))
            else:
                buffer.append(line)
        else:
            buffer.append(line)
            if (
                match
                and match.group(1)[0] == marker[0]
                and len(match.group(1)) >= marker[1]
                and not match.group(2).strip()
            ):
                segments.append((True, "\n".join(buffer)))
                buffer = []
                marker = None
    if buffer:
        segments.append((marker is not None, "\n".join(buffer)))
    return segments


def open_fence(text: str) -> str:
    """The fence that is still open at the end of the text or an empty string."""
    segments = split_fences(text)
    if not segments or not segments[-1][0]:
        return ""
    lines = segments[-1][1].split("\n")
    first = FENCE_RE.match(lines[0])
    assert first
    fence = first.group(1)
    if len(lines) > 1:
        last = FENCE_RE.match(lines[-1])
        if last and last.group(1)[0] == fence[0] and len(last.group(1)) >= len(fence) and not last.group(2).strip():
            return ""
    return fence


TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def table_cells(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", line)]


def convert_tables(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        # a separator needs a pipe or a rule or a heading underline would look like a table
        is_header = (
            "|" in line
            and index + 1 < len(lines)
            and "|" in lines[index + 1]
            and TABLE_SEPARATOR_RE.match(lines[index + 1])
        )
        if not is_header:
            out.append(line)
            index += 1
            continue
        index += 2  # the header row and the separator are dropped
        while index < len(lines) and "|" in lines[index] and lines[index].strip():
            cells = [cell for cell in table_cells(lines[index]) if cell]
            if cells:
                rest = ", ".join(cells[1:])
                out.append(f"- **{cells[0]}**" + (f" - {rest}" if rest else ""))
            index += 1
    return "\n".join(out)


INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
CALLOUT_RE = re.compile(r"^(\s*>\s*)\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*$", re.IGNORECASE | re.MULTILINE)
HTML_COMMENT_RE = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
TOKEN_RE = re.compile(
    r"""
    (?P<esc>\\.)
  | (?P<image>!\[(?P<ialt>(?:[^\[\]\n]|\[[^\]\n]*\])*)\]\([^)\n]*\))
  | (?P<link>\[(?P<ltext>(?:[^\[\]\n]|\[[^\]\n]*\])*)\]\((?P<lurl>[^)\s]*)(?:\s+(?:"[^"\n]*"|'[^'\n]*'))?\))
  | (?P<auto><(?P<aurl>https?://[^>\s]*)>)
  | (?P<img><img\b[^>\n]*>)
  | (?P<br><br\s*/?>)
  | (?P<tag></?[A-Za-z][^<>\n]*>)
  | (?P<angle><[^<>\n]*>)
  | (?P<invite>(?:https?://)?(?:www\.)?(?:discord(?:app)?\.com/invite/|discord\.gg/|discord\.me/|dsc\.gg/)[^\s<>()\[\]]*)
  | (?P<bare>(?:https?://|www\.)[^\s<>()\[\]]+)
  | (?P<ref>(?<![\w/&#@])\#(?P<num>\d{1,9})\b)
  | (?P<mention>@(?:everyone|here)\b)
  | (?P<bracket>[\[\]])
    """,
    re.VERBOSE | re.IGNORECASE,
)
IMG_ALT_RE = re.compile(r"""\balt\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)


def image_text(alt: str) -> str:
    alt = single_line(alt)
    return f"[Image: {escape_inline(cut_raw(alt, 120))}]" if alt else "[Image]"


def defang_inline(text: str) -> str:
    text = text.replace("<", LQUOTE).replace(">", RQUOTE)
    text = re.sub(r"@(everyone|here)\b", "@" + ZWSP + r"\1", text, flags=re.IGNORECASE)
    return re.sub(r"(?<!\\)([\[\]])", r"\\\1", text)


def rewrite_prose(text: str, cfg: Config) -> str:
    """Applies the text rules to prose, in one pass so no rule sees another's output."""

    def swap(match: re.Match[str]) -> str:
        if match.group("esc"):
            return match.group("esc")
        if match.group("image") is not None:
            return image_text(match.group("ialt"))
        if match.group("link") is not None:
            label, url = defang_inline(match.group("ltext")), match.group("lurl")
            host = host_of(url)
            scheme = url.split(":", 1)[0].lower()
            if scheme not in ("http", "https") or not host or re.search(r'[<>"\x00-\x1f]', url):
                return label
            if INVITE_RE.search(url):
                return f"{label} (invite link removed)"
            if not host_allowed(host, cfg):
                return f"{label} (link to {host})"
            return f"[{label}]({url})"
        if match.group("auto") is not None:
            url = match.group("aurl")
            host = host_of(url)
            if INVITE_RE.search(url):
                return "(invite link removed)"
            return f"<{url}>" if host_allowed(host, cfg) else f"(link to {host})"
        if match.group("img") is not None:
            found = IMG_ALT_RE.search(match.group("img"))
            return image_text((found.group(1) or found.group(2) or "") if found else "")
        if match.group("br") is not None:
            return " "
        if match.group("tag") is not None:
            return ""
        if match.group("angle") is not None:
            inner = match.group("angle")[1:-1].replace("<", "").replace(">", "")
            return LQUOTE + inner.replace("@", "@" + ZWSP) + RQUOTE
        if match.group("invite") is not None:
            return "(invite link removed)"
        if match.group("bare") is not None:
            url = match.group("bare")
            trail = ""
            while url and url[-1] in ".,;:!?'\"*_":
                trail, url = url[-1] + trail, url[:-1]
            host = host_of(url if "://" in url else "https://" + url)
            if INVITE_RE.search(url):
                return "(invite link removed)" + trail
            return (url if host_allowed(host, cfg) else f"(link to {host})") + trail
        if match.group("ref") is not None:
            number = match.group("num")
            return f"[#{number}](https://github.com/{cfg.repository}/issues/{number})"
        if match.group("mention") is not None:
            return "@" + ZWSP + match.group("mention")[1:]
        return "\\" + match.group("bracket")

    text = CALLOUT_RE.sub(lambda m: f"{m.group(1)}{CALLOUTS[m.group(2).upper()]}:", text)
    text = convert_tables(text)
    out = []
    position = 0
    for code in INLINE_CODE_RE.finditer(text):
        out.append(TOKEN_RE.sub(swap, text[position : code.start()]))
        out.append(code.group(0))
        position = code.end()
    out.append(TOKEN_RE.sub(swap, text[position:]))
    return "".join(out)


CUT_MARKER_RE = re.compile(r"<!--\s*discord-cut\s*-->")


def prepare_body(raw: Any, cfg: Config, url: str, label: str, limit: int = EMBED_DESCRIPTION_LIMIT) -> str:
    """Turns a release or discussion body into an embed description.

    The result always ends with a link to the full text, is cut at a marker or at a
    paragraph break and never ends inside a code block.
    """
    text = clean(raw)
    marker = CUT_MARKER_RE.search(text)
    if marker:
        text = text[: marker.start()]
    pieces = []
    for is_code, segment in split_fences(text):
        pieces.append(segment if is_code else rewrite_prose(HTML_COMMENT_RE.sub("", segment), cfg))
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(pieces)).strip()
    suffix = f"[{label}]({url})"
    budget = limit - len(suffix) - 2 - 70  # a blank line and room to close a code block
    if len(text) > budget:
        head = text[:budget]
        paragraph = head.rfind("\n\n")
        if paragraph >= budget // 3:
            head = head[:paragraph]
        else:
            line = head.rfind("\n")
            head = head[:line] if line >= budget // 3 else head
            # a hard cut must not leave a link or a bracket open
            if head.rfind("[") > head.rfind("]"):
                head = head[: head.rfind("[")]
            head = head.rstrip("\\")
        text = head.rstrip()
    fence = open_fence(text)
    if fence:
        text += "\n" + fence
    result = f"{text}\n\n{suffix}" if text else suffix
    return result if len(result) <= limit else suffix


# ---------------------------------------------------------------------------------
# events


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def whole_number(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def is_bot(sender: dict[str, Any]) -> bool:
    login = str(sender.get("login", ""))
    return sender.get("type") == "Bot" or login.lower().endswith("[bot]")


def key_for(identity: str) -> str:
    return hashlib.sha256(identity.encode()).hexdigest()[:16]


def parse_time(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def written_date(stamp: str) -> str:
    return f"{int(stamp[8:10])} {MONTHS[int(stamp[5:7]) - 1]} {stamp[:4]}"


def feed_payload(hook_name: str, content: str) -> dict[str, Any]:
    return {
        "username": hook_name[:USERNAME_LIMIT],
        "content": content[:CONTENT_LIMIT],
        "allowed_mentions": NO_MENTIONS,
        "flags": FEED_FLAGS,
    }


def shown_labels(raw: Any, cfg: Config) -> list[str]:
    allowed = {label.lower(): label for label in cfg.labels}
    shown = []
    for item in raw if isinstance(raw, list) else []:
        name = str(as_dict(item).get("name", "")).strip().lower()
        if name in allowed and allowed[name] not in shown:
            shown.append(allowed[name])
    return shown


def check_embed(embed: dict[str, Any]) -> None:
    """Fails before sending when an embed would break the limits in the message."""
    total = len(embed.get("title", "")) + len(embed.get("description", ""))
    total += len(embed.get("footer", {}).get("text", ""))
    for item in embed.get("fields", []):
        total += len(item["name"]) + len(item["value"])
    if total > EMBED_TOTAL_LIMIT:
        raise ConfigError("an embed is over the 6,000 character limit")


def build_release(event: dict[str, Any], cfg: Config) -> Result:
    if event.get("action") != "released":
        return Result(skip="the release action is not released")
    release = as_dict(event.get("release"))
    if release.get("draft") or release.get("prerelease"):
        return Result(skip="a draft or a pre-release is not posted")
    release_id, tag = whole_number(release.get("id")), release.get("tag_name")
    if release_id is None or not isinstance(tag, str) or not clean(tag).strip():
        return Result(skip="the release has no id or tag")
    hook = cfg.webhook_for_channel("releases")
    if hook is None:
        return Result(skip="the layout has no webhook for the releases channel")
    webhook_var, hook_name = hook
    shown_tag = single_line(tag)
    quoted = urllib.parse.quote(tag, safe="")
    # an absurdly long tag would push the message over its limit, so the list of releases stands in
    link = f"https://github.com/{cfg.repository}/releases" + (f"/tag/{quoted}" if len(quoted) <= 300 else "")
    title = f"{cfg.project} " + fit_title(shown_tag, EMBED_TITLE_LIMIT - len(cfg.project) - 1)
    embed: dict[str, Any] = {
        "title": title,
        "url": link,
        "description": prepare_body(release.get("body"), cfg, link, "Read the full notes"),
        "fields": [{"name": "Version", "value": plain(shown_tag, 200), "inline": True}],
        "footer": {"text": "Release on GitHub"},
        "color": cfg.colour,
    }
    stamp = parse_time(release.get("published_at")) or parse_time(release.get("created_at"))
    if stamp:
        embed["fields"].append({"name": "Published", "value": written_date(stamp), "inline": True})
        embed["timestamp"] = stamp
    check_embed(embed)
    payload = {
        "username": hook_name[:USERNAME_LIMIT],
        "content": f"New release: {cfg.project} {plain(shown_tag, 200)}. <{link}>",
        "allowed_mentions": NO_MENTIONS,
        "flags": 0,
        "embeds": [embed],
    }
    return Result([Post(key_for(f"release:{release_id}"), f"release {release_id}", webhook_var, payload)])


class GateError(Exception):
    """GitHub could not be asked who did something. The post is held and the run fails."""


class Gate:
    """Asks GitHub who a person is in the repository. Nothing here is trusted from the event."""

    def __init__(self, token: str, repository: str) -> None:
        self.token, self.repository = token, repository

    def get(self, path: str, missing_ok: bool = False) -> Any:
        status, _, body = api_get(path, self.token)
        if status == 404 and missing_ok:
            return None
        if status != 200:
            raise GateError(f"GitHub could not be asked (status {status or 'none'})")
        try:
            return json.loads(body)
        except ValueError as error:
            raise GateError("GitHub gave an answer that is not JSON") from error

    def can_write(self, login: str) -> bool:
        if not LOGIN_RE.match(login):
            return False
        # a person who is not a collaborator gets a 404 here. That is the answer "cannot write",
        # not a failure, because every outside issue from a template reaches this call.
        data = self.get(f"/repos/{self.repository}/collaborators/{login}/permission", missing_ok=True)
        return isinstance(data, dict) and data.get("permission") in WRITE_PERMISSIONS

    def issue_events(self, number: int) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for page in (1, 2, 3):
            data = self.get(f"/repos/{self.repository}/issues/{number}/events?per_page=100&page={page}")
            if not isinstance(data, list):
                raise GateError("GitHub gave an unexpected answer")
            events += [item for item in data if isinstance(item, dict)]
            if len(data) < 100:
                return events
        raise GateError("the issue has too many events to read")


def may_release(association: Any, login: str, gate: Gate | None) -> bool:
    """Whether what this person wrote is posted at once.

    OWNER is enough. MEMBER and COLLABORATOR also cover people with read-only access, so
    those must hold write or admin on the repository. Raises GateError if GitHub cannot say.
    """
    if association == "OWNER":
        return True
    if association not in TRUSTED or gate is None:
        return False
    return gate.can_write(login)


def issue_line(issue: dict[str, Any], number: int, cfg: Config, webhook_var: str, hook_name: str) -> Result:
    labels = shown_labels(issue.get("labels"), cfg)
    # an issue marked as a good first one gets its own lead, so a newcomer can find it
    first = any(
        str(as_dict(item).get("name", "")).strip().lower() == GOOD_FIRST_ISSUE for item in issue.get("labels") or []
    )
    lead = "Good first issue" if first else "New issue"
    line = f"{lead} #{number}: {plain(issue.get('title'), FEED_TITLE_LIMIT)}."
    if labels:
        line += f" Labels: {', '.join(labels)}."
    line += f" <https://github.com/{cfg.repository}/issues/{number}>"
    post = Post(key_for(f"issue:{number}"), f"issue {number}", webhook_var, feed_payload(hook_name, line), True)
    return Result([post])


def build_issue(event: dict[str, Any], cfg: Config, gate: Gate | None = None) -> Result:
    action = event.get("action")
    if action not in ("opened", "labeled"):
        return Result(skip="the issue action is not opened or labeled")
    issue = as_dict(event.get("issue"))
    number = whole_number(issue.get("number"))
    if number is None or "pull_request" in issue:
        return Result(skip="the issue has no number or is a pull request")
    names = {str(as_dict(item).get("name", "")).strip().lower() for item in issue.get("labels") or []}
    if names & set(cfg.skip_labels):
        return Result(skip="the issue carries a label that is never posted")
    hook = cfg.webhook_for_channel("github-feed")
    if hook is None:
        return Result(skip="the layout has no webhook for the feed channel")
    try:
        trusted_author = may_release(
            issue.get("author_association"), str(as_dict(issue.get("user")).get("login", "")), gate
        )
    except GateError as error:
        return Result(error=f"the author of issue {number} could not be checked: {error}")
    if action == "opened":
        if not trusted_author:
            return Result(skip="held until a maintainer acts: the author is not a maintainer")
        return issue_line(issue, number, cfg, *hook)
    # labeled: only a label from the allow-list, applied by someone with write access, on an
    # issue from a stranger. an issue from a maintainer was posted when it was opened.
    if trusted_author:
        return Result(skip="the issue was posted when it was opened")
    allowed = {label.lower() for label in cfg.labels}
    label = str(as_dict(event.get("label")).get("name", "")).strip().lower()
    sender = str(as_dict(event.get("sender")).get("login", ""))
    if label not in allowed:
        return Result(skip="the label is not on the allow-list")
    if gate is None:
        return Result(skip="held until a maintainer acts: nobody could be checked without a token")
    author = str(as_dict(issue.get("user")).get("login", ""))
    try:
        if not gate.can_write(sender):
            return Result(skip="held until a maintainer acts: the label was not added by someone with write access")
        # the first allow-listed label from someone with write access is the one that releases the post.
        # a later label from a maintainer must not post it again.
        known: dict[str, bool] = {sender: True}
        first = current = None
        for item in gate.issue_events(number):
            actor = str(as_dict(item.get("actor")).get("login", ""))
            tag = str(as_dict(item.get("label")).get("name", "")).strip().lower()
            if item.get("event") != "labeled" or tag not in allowed or actor.lower() == author.lower():
                continue
            if actor not in known:
                known[actor] = gate.can_write(actor)
            if known[actor] and first is None:
                first = item.get("id")
            if actor == sender and tag == label:
                current = item.get("id")
    except GateError as error:
        return Result(error=f"the label on issue {number} could not be checked: {error}")
    if first is None or first != current:
        return Result(skip="held until a maintainer acts: an earlier label from a maintainer already released it")
    return issue_line(issue, number, cfg, *hook)


def thread_name(title: Any) -> str:
    """A forum post name. It is shown as it is written, so nothing is escaped, but a mention is made inert."""
    raw = cut_raw(single_line(title), THREAD_NAME_LIMIT - 20)
    return (
        raw.replace("<", LQUOTE).replace(">", RQUOTE).replace("@", "@" + ZWSP)[:THREAD_NAME_LIMIT] or "New discussion"
    )


def build_discussion(event: dict[str, Any], cfg: Config, comment: bool = False, gate: Gate | None = None) -> Result:
    if event.get("action") != "created":
        return Result(skip="the discussion action is not created")
    discussion = as_dict(event.get("discussion"))
    number = whole_number(discussion.get("number"))
    slug = str(as_dict(discussion.get("category")).get("slug", ""))
    route = cfg.discussions.get(slug)
    if number is None or route is None:
        return Result(skip="the discussion category is not posted")
    hook = cfg.webhook_for_name(route["webhook"])
    if hook is None:
        return Result(skip="the layout has no webhook for the discussion route")
    webhook_var, hook_name = hook
    link = f"https://github.com/{cfg.repository}/discussions/{number}"
    key, label = key_for(f"discussion:{number}"), f"discussion {number}"
    announcement = route.get("form") == "announcement"
    if comment and announcement:
        return Result(skip="a comment on an announcement is not posted")
    if not announcement:
        # a stranger's discussion waits for a maintainer. a maintainer's own is posted at once.
        who = as_dict(event.get("comment")).get("user") if comment else discussion.get("user")
        try:
            trusted_author = may_release(
                discussion.get("author_association"), str(as_dict(discussion.get("user")).get("login", "")), gate
            )
            by_maintainer = comment and discussion.get("comments") == 1 and not trusted_author
            if by_maintainer:
                # a comment releases a stranger's discussion only from someone who can write
                by_maintainer = may_release(
                    as_dict(event.get("comment")).get("author_association"),
                    str(as_dict(who).get("login", "")),
                    gate,
                )
        except GateError as error:
            return Result(error=f"the people on discussion {number} could not be checked: {error}")
        if comment:
            if trusted_author:
                return Result(skip="the discussion was posted when it was created")
            if not by_maintainer:
                return Result(skip="held until a maintainer acts: not the first comment or not from a maintainer")
        elif not trusted_author:
            return Result(skip="held until a maintainer acts: the author is not a maintainer")
    if announcement:
        title = fit_title(discussion.get("title"), EMBED_TITLE_LIMIT)
        embed: dict[str, Any] = {
            "title": title,
            "url": link,
            "description": prepare_body(discussion.get("body"), cfg, link, "Read the full post"),
            "footer": {"text": "Announcement on GitHub"},
            "color": cfg.colour,
        }
        stamp = parse_time(discussion.get("created_at"))
        if stamp:
            embed["timestamp"] = stamp
        check_embed(embed)
        payload = {
            "username": hook_name[:USERNAME_LIMIT],
            "content": f"Announcement: {plain(discussion.get('title'), FEED_TITLE_LIMIT)} <{link}>",
            "allowed_mentions": NO_MENTIONS,
            "flags": 0,
            "embeds": [embed],
        }
        return Result([Post(key, label, webhook_var, payload)])
    lead = plain(route.get("lead", "New discussion"), 60)
    line = f"{lead}: {plain(discussion.get('title'), FEED_TITLE_LIMIT)} <{link}>"
    payload = feed_payload(hook_name, line)
    if route.get("thread", "").lower() == "true":
        # a webhook post to a forum channel must name the post: "thread_name" is required there
        payload["thread_name"] = thread_name(discussion.get("title"))
        tag_var = route.get("tag_secret", "")
        if tag_var and not SECRET_NAME_RE.match(tag_var):
            raise ConfigError("a forum tag secret name is not in capitals with underscores")
        return Result([Post(key, label, webhook_var, payload, True, tag_var)])
    return Result([Post(key, label, webhook_var, payload, True)])


def build_push(event: dict[str, Any], cfg: Config) -> Result:
    repository = as_dict(event.get("repository"))
    branch = str(repository.get("default_branch") or "main")
    if event.get("ref") != f"refs/heads/{branch}":
        return Result(skip="the push is not to the default branch")
    if event.get("deleted"):
        return Result(skip="the branch was deleted")
    hook = cfg.webhook_for_channel("github-feed")
    if hook is None:
        return Result(skip="the layout has no webhook for the feed channel")
    types = "|".join(re.escape(item) for item in cfg.commit_types)
    subject_re = re.compile(rf"^(?:{types})(?:\([^)\n]*\))?!?: .+\(#(\d{{1,9}})\)$")
    matched: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for commit in event.get("commits") or []:
        commit = as_dict(commit)
        commit_id = commit.get("id")
        if not isinstance(commit_id, str) or not SHA_RE.match(commit_id) or commit_id in seen:
            continue
        seen.add(commit_id)
        author = as_dict(commit.get("author"))
        if str(author.get("username", "")).lower().endswith("[bot]"):
            continue
        subject = clean(commit.get("message")).split("\n", 1)[0].strip()
        found = subject_re.match(subject)
        if found:
            matched.append((commit_id, subject, found.group(1)))
    if not matched:
        return Result(skip="no commit is a merged change of a posted type")
    posts = []
    for commit_id, subject, number in matched[:MAX_PUSH_LINES]:
        line = f"Merged: {plain(subject, FEED_TITLE_LIMIT)} <https://github.com/{cfg.repository}/pull/{number}>"
        posts.append(
            Post(
                key_for(f"commit:{commit_id}"),
                f"commit {commit_id[:7]}",
                hook[0],
                feed_payload(hook[1], line),
                True,
            )
        )
    extra = len(matched) - MAX_PUSH_LINES
    if extra > 0:
        before, after = str(event.get("before", "")), str(event.get("after", ""))
        line = f"Plus {extra} more changes"
        if SHA_RE.match(before) and SHA_RE.match(after) and set(before) != {"0"}:
            line += f": <https://github.com/{cfg.repository}/compare/{before}...{after}>"
        else:
            line += "."
        posts.append(Post(key_for(f"push-more:{after}"), "more changes", hook[0], feed_payload(hook[1], line), True))
    return Result(posts)


def build_ci_alert(env: Any, event: dict[str, Any], cfg: Config) -> Result:
    """A failed run on the default branch, as a staff alert with fixed words and a link.

    It is built from the run's own identifiers and never from a log, so no secret that a log might hold can
    reach Discord. A pull request, whoever opened it, is never alerted: only a push to the default branch.
    """
    if env.get("GITHUB_EVENT_NAME") != "push":
        return Result(skip="only a push to the default branch is alerted, never a pull request")
    repository = as_dict(event.get("repository"))
    branch = str(repository.get("default_branch") or "main")
    if (
        env.get("GITHUB_REF") != f"refs/heads/{branch}"
        or env.get("GITHUB_REPOSITORY", "").lower() != cfg.repository.lower()
    ):
        return Result(skip="the run is not on the default branch of this repository")
    run_id = str(env.get("GITHUB_RUN_ID", ""))
    if not run_id.isdigit() or len(run_id) > 20:
        return Result(error="the run has no usable number")
    hook = cfg.webhook_for_channel("ci-alerts")
    if hook is None:
        return Result(skip="the layout has no webhook for the CI alerts channel")
    webhook_var, hook_name = hook
    link = f"https://github.com/{cfg.repository}/actions/runs/{run_id}"
    branch = plain(branch, 60)
    line = f"CI failed on {branch}: run {run_id}. <{link}>"
    payload = {"username": hook_name[:USERNAME_LIMIT], "content": line[:CONTENT_LIMIT], "allowed_mentions": NO_MENTIONS}
    return Result([Post(key_for(f"ci:{run_id}"), f"ci failure {run_id}", webhook_var, payload)])


def build_posts(event_name: str, event: dict[str, Any], cfg: Config, gate: Gate | None = None) -> Result:
    """Turns one event into the posts it deserves. Anything else is a skip."""
    if str(as_dict(event.get("repository")).get("full_name", "")).lower() != cfg.repository.lower():
        return Result(skip="the event is from another repository")
    if is_bot(as_dict(event.get("sender"))):
        return Result(skip="the event was caused by a bot account")
    builders = {
        "release": build_release,
        "issues": build_issue,
        "push": build_push,
    }
    if event_name == "issues":
        return build_issue(event, cfg, gate)
    if event_name in ("discussion", "discussion_comment"):
        return build_discussion(event, cfg, event_name == "discussion_comment", gate)
    builder = builders.get(event_name)
    if builder is None:
        return Result(skip="the event type is not relayed")
    return builder(event, cfg)


def sample_events(cfg: Config) -> list[tuple[str, dict[str, Any]]]:
    """Events for a hand run, so the owner can read what each post looks like."""
    repo = {"full_name": cfg.repository, "default_branch": "main"}
    label = cfg.labels[0] if cfg.labels else "bug"
    samples = [
        (
            "release",
            {
                "action": "released",
                "repository": repo,
                "release": {
                    "id": 1,
                    "tag_name": "v0.0.0",
                    "published_at": "2026-01-01T09:00:00Z",
                    "body": (
                        "### Added\n- A sample note.\n\n"
                        "| Part | Note |\n| --- | --- |\n| Sample | A table becomes a list |"
                    ),
                },
            },
        ),
        (
            "issues",
            {
                "action": "opened",
                "repository": repo,
                "issue": {
                    "author_association": "OWNER",
                    "number": 1,
                    "title": "A sample issue",
                    "labels": [{"name": label}],
                },
            },
        ),
        (
            "push",
            {
                "ref": "refs/heads/main",
                "before": "1" * 40,
                "after": "2" * 40,
                "repository": repo,
                "commits": [{"id": "a" * 40, "message": "fix: a sample change (#1)", "author": {"username": "sample"}}],
            },
        ),
    ]
    for slug in cfg.discussions:
        samples.append(
            (
                "discussion",
                {
                    "action": "created",
                    "repository": repo,
                    "discussion": {
                        "author_association": "OWNER",
                        "number": 1,
                        "title": f"A sample post in {slug}",
                        "body": "A sample body.",
                        "created_at": "2026-01-01T09:00:00Z",
                        "category": {"slug": slug},
                    },
                },
            )
        )
    return samples


# ---------------------------------------------------------------------------------
# delivery

_sleep = time.sleep
_now = time.monotonic
_wall = time.time


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A webhook or an API call that redirects is an error, never followed."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


OPENER = urllib.request.build_opener(_NoRedirect)


class Output:
    """Prints lines and the job summary. A known secret value is never written."""

    def __init__(self, secrets: list[str]) -> None:
        self.secrets = [item for item in secrets if item]
        self.rows: list[tuple[str, str]] = []
        self.notes: list[str] = []

    def redact(self, text: str) -> str:
        for item in self.secrets:
            text = text.replace(item, "***")
            tail = item.rstrip("/").rsplit("/", 1)[-1]
            if len(tail) > 8:
                text = text.replace(tail, "***")
        return text

    def line(self, text: str) -> None:
        print("relay: " + self.redact(text), flush=True)

    def notice(self, text: str) -> None:
        print(f"::notice title=Discord relay::{self.redact(text)}", flush=True)
        self.notes.append(text)

    def error(self, text: str) -> None:
        print(f"::error title=Discord relay::{self.redact(text)}", flush=True)
        self.notes.append("Error: " + text)

    def add(self, label: str, result: str) -> None:
        self.rows.append((label, result))

    def write_summary(self, extra: list[str] | None = None) -> None:
        path = os.environ.get("GITHUB_STEP_SUMMARY")
        if not path:
            return
        lines = ["### Discord relay", ""]
        lines += [f"- {self.redact(note)}" for note in self.notes]
        if self.rows:
            lines += ["", "| Post | Result |", "| --- | --- |"]
            lines += [f"| {self.redact(a)} | {self.redact(b)} |" for a, b in self.rows]
        lines += [self.redact(item) for item in extra or []]
        try:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
        except OSError:
            pass


def check_hook_url(url: str, name: str) -> str:
    """Accepts only a Discord webhook address. Loopback is allowed for tests alone."""
    parts = urllib.parse.urlsplit(url)
    loopback = os.environ.get("RELAY_ALLOW_LOOPBACK") == "1" and parts.hostname in LOOPBACK_HOSTS
    host = (parts.hostname or "").lower()
    official = parts.scheme == "https" and any(host == h or host.endswith("." + h) for h in HOOK_HOSTS)
    if not (official or (loopback and parts.scheme == "http")) or not parts.path.startswith(HOOK_PATH_PREFIX):
        raise ConfigError(f"the value of {name} is not a Discord webhook address")
    if parts.username or parts.password:
        raise ConfigError(f"the value of {name} is not a Discord webhook address")
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query = [(k, v) for k, v in query if k != "wait"] + [("wait", "true")]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query), fragment=""))


def http_call(request: urllib.request.Request) -> tuple[int | None, Any, bytes]:
    try:
        with OPENER.open(request, timeout=REQUEST_TIMEOUT) as response:
            return response.status, response.headers, response.read(1_000_000)
    except urllib.error.HTTPError as error:
        try:
            body = error.read(65_536)
        except (OSError, http.client.HTTPException):
            body = b""
        return error.code, error.headers, body
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError):
        return None, {}, b""


def retry_after(headers: Any, body: bytes) -> float | None:
    """Seconds to wait after a 429. The body has the precise figure [D-RATE]."""
    try:
        return max(float(json.loads(body.decode("utf-8", "replace"))["retry_after"]), 0.0)
    except (ValueError, TypeError, KeyError):
        pass
    try:
        return max(float(headers.get("Retry-After")), 0.0)
    except (ValueError, TypeError, AttributeError):
        return None


def deliver(url: str, payload: dict[str, Any], started: float) -> tuple[bool, str]:
    """Posts one message. Returns whether it was accepted and a short reason."""
    body = json.dumps(payload).encode("ascii")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "github-relay/1.0",
            "Accept": "application/json",
        },
    )
    tries = rate_waits = 0
    while True:
        status, headers, data = http_call(request)
        if status is not None and 200 <= status < 300:
            pause = None
            if headers and headers.get("X-RateLimit-Remaining") == "0":
                try:
                    pause = float(headers.get("X-RateLimit-Reset-After", ""))
                except ValueError:
                    pause = None
            if pause is not None and 0 < pause <= 5:
                _sleep(pause)
            return True, str(status)
        if status == 429:
            wait = retry_after(headers, data)
            rate_waits += 1
            if wait is None or wait > MAX_RATE_LIMIT_WAIT or rate_waits > MAX_RATE_LIMIT_WAITS:
                return False, "429 and the wait was too long"
            if _now() - started + wait > RUN_BUDGET:
                return False, "429 and the run is out of time"
            _sleep(wait)
            continue
        if status is None or 500 <= status < 600:
            if tries >= len(RETRY_DELAYS):
                return False, "no answer" if status is None else str(status)
            if _now() - started + RETRY_DELAYS[tries] > RUN_BUDGET:
                return False, "the run is out of time"
            _sleep(RETRY_DELAYS[tries])
            tries += 1
            continue
        if status == 404:
            return False, "404 and the webhook no longer exists"
        return False, str(status)


def api_get(path: str, token: str) -> tuple[int | None, Any, bytes]:
    base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    request = urllib.request.Request(
        base + path,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "github-relay/1.0",
        },
    )
    return http_call(request)


def earlier_attempt(token: str) -> tuple[bool, set[str]]:
    """Asks GitHub what the attempt before this one did.

    Returns whether it finished without failing and, if it did not, the keys of the
    posts that its log says were sent. Nothing is stored between attempts: GitHub's
    record of the run is the only state. Raises OSError when GitHub cannot be asked.
    """
    repository, run_id = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_RUN_ID"]
    previous = int(os.environ["GITHUB_RUN_ATTEMPT"]) - 1
    status, _, body = api_get(f"/repos/{repository}/actions/runs/{run_id}/attempts/{previous}/jobs?per_page=100", token)
    if status != 200:
        raise OSError("the earlier attempt could not be read")
    jobs = [job for job in json.loads(body).get("jobs", []) if isinstance(job, dict)]
    mine = [job for job in jobs if job.get("name") == os.environ.get("GITHUB_JOB")] or jobs
    if mine and all(job.get("conclusion") == "success" for job in mine):
        return True, set()
    keys: set[str] = set()
    for job in mine:
        if job.get("conclusion") != "failure" or whole_number(job.get("id")) is None:
            continue
        keys |= set(MARKER_RE.findall(job_log(repository, job["id"], token)))
    return False, keys


def job_log(repository: str, job_id: int, token: str) -> str:
    status, headers, logged = api_get(f"/repos/{repository}/actions/jobs/{job_id}/logs", token)
    location = headers.get("Location") if headers else None
    if status == 200:
        return logged.decode("utf-8", "replace")
    if status in (301, 302, 307) and location:
        # the log lives on another host, which must not see the token
        return fetch_log(location)
    return ""


def recent_feed_posts(token: str, webhook_var: str) -> tuple[int, bool, bool]:
    """Counts the feed posts of the last hour from the workflow's own recent runs.

    GitHub keeps each run's log and every post leaves a line in it, so the count needs no
    stored state. Anyone can start runs, so the work is bounded: more than MAX_RUNS_COUNTED
    runs in the window or running out of calls or time, counts as "cap reached" and is
    never an error. Returns the count, whether a held-back notice was already posted and
    whether the count was cut short. Raises OSError only when GitHub cannot be read.
    """
    repository, current = os.environ["GITHUB_REPOSITORY"], os.environ.get("GITHUB_RUN_ID", "")
    workflow = os.environ.get("GITHUB_WORKFLOW_REF", "").split("@")[0].rsplit("/", 1)[-1] or "discord-relay.yml"
    since = datetime.datetime.fromtimestamp(_wall() - CAP_WINDOW_SECONDS, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    began, calls = _now(), 0

    def out_of_budget() -> bool:
        return _now() - began > COUNT_DEADLINE or calls >= MAX_COUNT_CALLS

    runs: list[dict[str, Any]] = []
    total = 0
    for page in (1, 2, 3):
        query = urllib.parse.urlencode({"created": f">={since}", "per_page": 100, "page": page})
        calls += 1
        status, _, body = api_get(f"/repos/{repository}/actions/workflows/{workflow}/runs?{query}", token)
        if status != 200:
            raise OSError("the recent runs could not be read")
        data = json.loads(body)
        total = int(data.get("total_count", 0))
        found = [run for run in data.get("workflow_runs", []) if isinstance(run, dict)]
        runs += found
        if len(found) < 100 or len(runs) >= total:
            break
    collected = len(runs)
    # a run that was cancelled or skipped posted nothing and neither did this one
    runs = [r for r in runs if str(r.get("id")) != current and r.get("conclusion") not in ("cancelled", "skipped")]
    overflow = collected < total or len(runs) > MAX_RUNS_COUNTED
    count, notice = 0, False
    for run in runs[:MAX_RUNS_COUNTED]:
        if out_of_budget():
            overflow = True
            break
        calls += 1
        status, _, body = api_get(f"/repos/{repository}/actions/runs/{run.get('id')}/jobs?per_page=10", token)
        if status != 200:
            raise OSError("the jobs of a recent run could not be read")
        for job in json.loads(body).get("jobs", []):
            if not isinstance(job, dict) or whole_number(job.get("id")) is None:
                continue
            if out_of_budget():
                overflow = True
                break
            calls += 1
            log = job_log(repository, job["id"], token)
            count += sum(1 for found in POSTED_RE.findall(log) if found == webhook_var)
            notice = notice or NOTICE_MARKER in log
    return count, notice, overflow


def fetch_log(location: str) -> str:
    parts = urllib.parse.urlsplit(location)
    if parts.scheme not in ("https", "http"):
        return ""
    request = urllib.request.Request(location, headers={"User-Agent": "github-relay/1.0"})
    status, _, body = http_call(request)
    return body.decode("utf-8", "replace") if status == 200 else ""


# ---------------------------------------------------------------------------------


def dry_run_requested(event: dict[str, Any]) -> bool:
    value = as_dict(event.get("inputs")).get("dry_run", True)
    return str(value).strip().lower() not in ("false", "0", "no")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Post GitHub activity to Discord.")
    parser.add_argument("--layout", required=True, help="the project's layout file")
    parser.add_argument(
        "--ci-failure", action="store_true", help="post a staff alert for a failed run on the default branch"
    )
    args = parser.parse_args(argv)
    env = os.environ
    out = Output([])
    try:
        cfg = load_config(args.layout)
        event_name = env.get("GITHUB_EVENT_NAME", "")
        try:
            with open(env.get("GITHUB_EVENT_PATH", ""), "rb") as handle:
                event = json.load(handle)
        except (OSError, ValueError) as error:
            raise ConfigError(f"the event file could not be read ({type(error).__name__})") from error
        if not isinstance(event, dict):
            raise ConfigError("the event file is not a JSON object")
    except ConfigError as error:
        out.error(str(error))
        out.write_summary()
        return 2

    webhooks = {hook["secret"]: env.get(hook["secret"], "").strip() for hook in cfg.webhooks}
    out = Output(list(webhooks.values()))

    if args.ci_failure:
        result = build_ci_alert(env, event, cfg)
        if result.error:
            out.error(result.error)
            out.write_summary()
            return 1
        if result.skip:
            out.line(f"nothing to post: {result.skip}.")
            out.write_summary()
            return 0
        return send_all(result.posts, webhooks, out, env)

    if event_name == "workflow_dispatch":
        return run_by_hand(cfg, event, webhooks, out)

    token = env.get("GITHUB_TOKEN", "")
    gate = Gate(token, cfg.repository) if token else None
    try:
        result = build_posts(event_name, event, cfg, gate)
    except ConfigError as error:
        out.error(str(error))
        out.write_summary()
        return 2
    if result.error:
        out.error(result.error)
        out.write_summary()
        return 1
    if result.skip:
        out.line(f"nothing to post: {result.skip}.")
        out.notes.append(f"Nothing to post: {result.skip}.")
        out.write_summary()
        return 0
    return send_all(result.posts, webhooks, out, env)


def run_by_hand(cfg: Config, event: dict[str, Any], webhooks: dict[str, str], out: Output) -> int:
    """A manual run: show every kind of post and with the switch off send one test line."""
    dry = dry_run_requested(event)
    extra = ["", "Rendered posts, one per line, as the webhook would receive them:", ""]
    for name, sample in sample_events(cfg):
        result = build_posts(name, sample, cfg)
        for post in result.posts:
            state = "set" if webhooks.get(post.webhook_var) else "missing"
            rendered = json.dumps(post.payload)
            out.line(f"dry run, {post.webhook_var} is {state}: {rendered}")
            out.add(f"sample {post.label} via {post.webhook_var}", f"secret {state}")
            extra.append("~~~~json\n" + rendered + "\n~~~~")
    if dry:
        out.notice("Dry run: nothing was sent. Switch dry_run off to send one test line to the feed channel.")
        out.write_summary(extra)
        return 0
    hook = cfg.webhook_for_channel("github-feed")
    if hook is None:
        out.error("the layout has no webhook for the feed channel")
        out.write_summary()
        return 2
    line = "Relay check from the Actions tab. No action is needed."
    post = Post(key_for("check"), "relay check", hook[0], feed_payload(hook[1], line))
    return send_all([post], webhooks, out, os.environ)


def send_all(posts: list[Post], webhooks: dict[str, str], out: Output, env: Any) -> int:
    started = _now()
    skip_keys: set[str] = set()
    attempt = int(env.get("GITHUB_RUN_ATTEMPT", "1") or "1")
    token = env.get("GITHUB_TOKEN", "")
    if attempt > 1 and token and env.get("GITHUB_RUN_ID") and env.get("GITHUB_REPOSITORY"):
        try:
            finished, skip_keys = earlier_attempt(token)
        except (OSError, ValueError, KeyError):
            out.notice("The earlier attempt could not be checked, so every post is sent again.")
        else:
            if finished:
                out.line("already posted: the earlier attempt of this run finished.")
                out.notes.append("Already posted: the earlier attempt of this run finished without failing.")
                out.write_summary()
                return 0
    failed = False
    room, notice_seen = FEED_CAP_PER_HOUR, True
    capped = [post for post in posts if post.capped and post.key not in skip_keys]
    if capped and token and env.get("GITHUB_REPOSITORY"):
        try:
            used, notice_seen, overflow = recent_feed_posts(token, capped[0].webhook_var)
            room = 0 if overflow else max(FEED_CAP_PER_HOUR - used, 0)
            if overflow:
                out.notice(
                    "Too many recent runs to count the feed posts of the last hour, so the cap counts as reached."
                )
        except (OSError, ValueError, KeyError):
            out.error(
                "The feed posts of the last hour could not be counted, so the feed posts were held. Re-run the job."
            )
            out.write_summary()
            return 1
    elif capped:
        out.notice("No token, so the hourly cap on the feed channel was not checked.")
    held = 0
    for post in posts:
        if post.capped and post.key not in skip_keys and capped and token and room <= 0:
            held += 1
            out.add(post.label, "held back by the hourly cap")
            continue
        if post.capped and post.key not in skip_keys:
            room -= 1
        if post.key in skip_keys:
            out.line(f"already posted: {post.label}.")
            out.add(post.label, "already posted by the earlier attempt")
            continue
        address = webhooks.get(post.webhook_var, "")
        if not address:
            out.notice(f"The secret {post.webhook_var} is not set, so {post.label} was not posted.")
            out.add(post.label, f"not posted, {post.webhook_var} is not set")
            continue
        try:
            url = check_hook_url(address, post.webhook_var)
        except ConfigError as error:
            out.error(str(error))
            out.add(post.label, "not posted, the address is not valid")
            failed = True
            continue
        payload = post.payload
        if post.tag_var:
            # a forum that requires a tag refuses a post without one (error 40067), so the id comes from a secret
            tag_id = str(env.get(post.tag_var, "")).strip()
            if not tag_id.isdigit():
                out.error(f"The secret {post.tag_var} is not set to a tag id, so {post.label} was not posted.")
                out.add(post.label, f"not posted, {post.tag_var} is not set")
                failed = True
                continue
            payload = {**payload, "applied_tags": [tag_id]}
        ok, reason = deliver(url, payload, started)
        if ok:
            out.line(f"relay-posted {post.key} {post.label} to {post.webhook_var} with status {reason}")
            out.add(post.label, f"posted to {post.webhook_var}")
        else:
            out.error(f"{post.label} to {post.webhook_var} failed: {reason}.")
            out.add(post.label, f"failed: {reason}")
            failed = True
    if held:
        out.line(f"{held} feed post(s) held back by the cap of {FEED_CAP_PER_HOUR} an hour.")
        out.notes.append(f"{held} feed post(s) were held back by the cap of {FEED_CAP_PER_HOUR} an hour.")
        address = webhooks.get(capped[0].webhook_var, "")
        if address and not notice_seen:
            try:
                url = check_hook_url(address, capped[0].webhook_var)
                text = f"{held} more new items are held back to keep this channel readable. They are all on GitHub."
                ok, reason = deliver(url, feed_payload(capped[0].payload["username"], text), started)
            except ConfigError:
                ok, reason = False, "the address is not valid"
            if ok:
                out.line(f"{NOTICE_MARKER} posted with status {reason}")
            else:
                out.error(f"the held back notice failed: {reason}.")
                failed = True
    out.write_summary()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
