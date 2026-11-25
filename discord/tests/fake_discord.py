"""A fake Discord REST API on 127.0.0.1 that keeps one server in memory.

It refuses what Discord refuses, so a test against it proves something. Nothing here ever leaves the
machine. The permission arithmetic is written out separately from the script's own so that a mistake in
one is caught by the other.
"""

from __future__ import annotations

import copy
import itertools
import json
import re
import threading
import urllib.parse
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# bit positions as the permissions documentation lists them
BITS = {
    "create_instant_invite": 1 << 0,
    "kick_members": 1 << 1,
    "ban_members": 1 << 2,
    "administrator": 1 << 3,
    "manage_channels": 1 << 4,
    "manage_guild": 1 << 5,
    "add_reactions": 1 << 6,
    "view_audit_log": 1 << 7,
    "priority_speaker": 1 << 8,
    "stream": 1 << 9,
    "view_channel": 1 << 10,
    "send_messages": 1 << 11,
    "send_tts_messages": 1 << 12,
    "manage_messages": 1 << 13,
    "embed_links": 1 << 14,
    "attach_files": 1 << 15,
    "read_message_history": 1 << 16,
    "mention_everyone": 1 << 17,
    "use_external_emojis": 1 << 18,
    "view_guild_insights": 1 << 19,
    "connect": 1 << 20,
    "speak": 1 << 21,
    "mute_members": 1 << 22,
    "deafen_members": 1 << 23,
    "move_members": 1 << 24,
    "use_vad": 1 << 25,
    "change_nickname": 1 << 26,
    "manage_nicknames": 1 << 27,
    "manage_roles": 1 << 28,
    "manage_webhooks": 1 << 29,
    "manage_guild_expressions": 1 << 30,
    "use_application_commands": 1 << 31,
    "request_to_speak": 1 << 32,
    "manage_events": 1 << 33,
    "manage_threads": 1 << 34,
    "create_public_threads": 1 << 35,
    "create_private_threads": 1 << 36,
    "use_external_stickers": 1 << 37,
    "send_messages_in_threads": 1 << 38,
    "use_embedded_activities": 1 << 39,
    "moderate_members": 1 << 40,
    "view_creator_monetization_analytics": 1 << 41,
    "use_soundboard": 1 << 42,
    "create_guild_expressions": 1 << 43,
    "create_events": 1 << 44,
    "use_external_sounds": 1 << 45,
    "send_voice_messages": 1 << 46,
    "set_voice_channel_status": 1 << 48,
    "send_polls": 1 << 49,
    "use_external_apps": 1 << 50,
    "pin_messages": 1 << 51,
    "bypass_slowmode": 1 << 52,
}
ALL = sum(BITS.values())
# what a new server gives to @everyone: wide, so tightening it is a real change
DEFAULT_EVERYONE = sum(
    BITS[n]
    for n in [
        "create_instant_invite",
        "add_reactions",
        "view_channel",
        "send_messages",
        "embed_links",
        "attach_files",
        "read_message_history",
        "mention_everyone",
        "use_external_emojis",
        "connect",
        "speak",
        "use_vad",
        "change_nickname",
        "use_application_commands",
        "create_public_threads",
        "create_private_threads",
        "use_external_stickers",
        "send_messages_in_threads",
        "use_embedded_activities",
        "send_tts_messages",
        "use_external_apps",
    ]
)

TEXT, VOICE, CATEGORY, ANNOUNCEMENT, STAGE, FORUM = 0, 2, 4, 5, 13, 15
VALID_TYPES = {TEXT, VOICE, CATEGORY, ANNOUNCEMENT, STAGE, FORUM}
USER_AGENT = re.compile(r"^DiscordBot \(\S+, \S+\)$")
_counter = itertools.count(1)


def snowflake() -> str:
    return str(1_100_000_000_000_000_000 + next(_counter) * 7919)


class FakeClock:
    """Time the script and the fake share, so rate limits cost no real seconds."""

    def __init__(self):
        self.t = 1000.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


class Refusal(Exception):
    def __init__(self, status: int, code: int, message: str, headers: dict | None = None, body: dict | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}
        self.body = body


def bad(message: str, code: int = 50035) -> Refusal:
    return Refusal(400, code, message)


def forbidden(message: str = "Missing Permissions") -> Refusal:
    return Refusal(403, 50013, message)


def normalise_channel_name(name: str) -> str:
    return name.strip().lower().replace(" ", "-")


class FakeDiscord:
    def __init__(
        self,
        guild_name: str = "Test Server",
        bot_permissions: int | None = None,
        clock: FakeClock | None = None,
    ):
        self.clock = clock or FakeClock()
        self.token = "fake-" + snowflake()[-6:]  # not a real token and never shaped like one
        self.lock = threading.RLock()
        self.bot_user_id = snowflake()
        self.app_id = snowflake()
        self.owner_id = snowflake()
        self.guild_id = snowflake()
        self.verify_key = "ab" * 32
        self.app = {
            "id": self.app_id,
            "name": "Test Bot",
            "verify_key": self.verify_key,
            "interactions_endpoint_url": None,
        }
        # switches for the facts the specification could not confirm
        self.forums_need_community = False
        self.news_with_community = True
        # unconfirmed: whether a forum counts towards the five channels that everyone can send in. The fake says no, so
        # a layout that only passes with forums counting fails here the way it may on the real server
        self.forums_count_for_onboarding = False
        self.onboarding_needs_postable = 5
        # what a stored message is believed to look like on the real server: an image used only by an embed comes
        # back as a signed CDN address with a query string and the attachment list does not hold it
        self.discord_like_embed_files = False
        self.member_count = 41
        self.other_guilds: list[dict] = []
        self.audit: list[dict] = []
        self.requests: list[tuple[str, str, int]] = []
        self.write_count = 0
        self.rejections = 0
        self.after_write = None
        self.faults: list[dict] = []
        self.limits: dict[str, tuple[int, float, str]] = {}
        self.global_limit: tuple[int, float] | None = None
        self._windows: dict[str, list[float]] = {}
        self._global_window: list[float] = []
        self.roles: dict[str, dict] = {}
        self.channels: dict[str, dict] = {}
        self.threads: dict[str, dict] = {}
        # "Archived threads are generally immutable" (the channel page), so a message in one is not deleted
        self.archived_threads_immutable = True
        # a role made by the API lands at the bottom, tied with the bot's own role when that sits at the bottom
        # too, which a live server showed. The documentation says "roles with the same position are sorted by id"
        # and not which way, so what a tie means for editing is unconfirmed: by default a tie may be edited and
        # with ties_block a role tied with the bot is treated as at or above it
        self.new_roles_tie = True
        self.ties_block = False
        # the pin list order is not stated in the documentation. Discord's client shows the newest pin first
        self.pins_newest_first = True
        self._files: list = []
        self.messages: dict[str, list[dict]] = {}
        self.automod: dict[str, dict] = {}
        self.webhooks: dict[str, dict] = {}
        self.commands: list[dict] = []
        self.onboarding = {"prompts": [], "default_channel_ids": [], "enabled": False, "mode": 0}
        self.guild = {
            "id": self.guild_id,
            "name": guild_name,
            "owner_id": self.owner_id,
            "features": [],
            "verification_level": 0,
            "explicit_content_filter": 0,
            "default_message_notifications": 0,
            "preferred_locale": "en-US",
            "description": None,
            "system_channel_flags": 0,
            "system_channel_id": None,
            "rules_channel_id": None,
            "public_updates_channel_id": None,
            "safety_alerts_channel_id": None,
            "incidents_data": None,
        }
        self.roles[self.guild_id] = {
            "id": self.guild_id,
            "name": "@everyone",
            "permissions": str(DEFAULT_EVERYONE),
            "position": 0,
            "color": 0,
            "hoist": False,
            "managed": False,
            "mentionable": False,
        }
        wanted = bot_permissions if bot_permissions is not None else 0
        self.bot_role_id = snowflake()
        self.roles[self.bot_role_id] = {
            "id": self.bot_role_id,
            "name": "Test Bot",
            "permissions": str(wanted),
            "position": 1,
            "color": 0,
            "hoist": False,
            "managed": True,
            "mentionable": False,
            "tags": {"bot_id": self.bot_user_id},
        }
        self.bot_member_roles = [self.bot_role_id]
        self._server: ThreadingHTTPServer | None = None

    # lifecycle ---------------------------------------------------------------------------------

    def start(self) -> str:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                fake._serve(self)

            do_POST = do_PUT = do_PATCH = do_DELETE = do_GET

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self.url

    @property
    def url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_address[1]}/api/v10"

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()

    # seeding helpers for tests -----------------------------------------------------------------

    def make_community(self, wizard_channels: bool = True, wizard_visible_to_bot: bool = False) -> None:
        features = set(self.guild["features"]) | {"COMMUNITY"}
        if self.news_with_community:
            features.add("NEWS")
        self.guild["features"] = sorted(features)
        if wizard_channels:
            rules = self.add_channel("rules", TEXT)
            hidden = [{"id": self.guild_id, "type": 0, "allow": "0", "deny": str(BITS["view_channel"])}]
            if wizard_visible_to_bot:
                hidden.append({"id": self.bot_role_id, "type": 0, "allow": str(BITS["view_channel"]), "deny": "0"})
            updates = self.add_channel("moderator-only", TEXT, overwrites=hidden)
            self.guild["rules_channel_id"] = rules["id"]
            self.guild["public_updates_channel_id"] = updates["id"]

    def add_role(self, name: str, permissions: int = 0, position: int | None = None, managed: bool = False) -> dict:
        top = max(r["position"] for r in self.roles.values())
        role = {
            "id": snowflake(),
            "name": name,
            "permissions": str(permissions),
            "position": top + 1 if position is None else position,
            "color": 0,
            "hoist": False,
            "managed": managed,
            "mentionable": False,
        }
        self.roles[role["id"]] = role
        return role

    def add_channel(
        self, name: str, kind: int = TEXT, parent: str | None = None, overwrites: list[dict] | None = None, **extra
    ) -> dict:
        parent_id = None
        if parent:
            parent_id = next(c["id"] for c in self.channels.values() if c["type"] == CATEGORY and c["name"] == parent)
        siblings = [
            c
            for c in self.channels.values()
            if (c["type"] == CATEGORY) == (kind == CATEGORY) and c.get("parent_id") == parent_id
        ]
        channel = {
            "id": snowflake(),
            "type": kind,
            "name": name,
            "position": max([c["position"] for c in siblings], default=-1) + 1,
            "parent_id": parent_id,
            "permission_overwrites": overwrites or [],
            "topic": None,
            "rate_limit_per_user": 0,
            "flags": 0,
            **extra,
        }
        if kind == FORUM:
            channel.setdefault("available_tags", [])
        self.channels[channel["id"]] = channel
        return channel

    def by_name(self, name: str, kind: int | None = None) -> dict:
        return next(c for c in self.channels.values() if c["name"] == name and (kind is None or c["type"] == kind))

    def add_thread(
        self,
        channel_name: str,
        name: str,
        archived: bool = False,
        private: bool = False,
        age: timedelta | None = None,
        messages: int = 1,
    ) -> dict:
        parent = self.by_name(channel_name)
        when = datetime.now(UTC) - (age or timedelta())
        thread = {
            "id": snowflake(),
            "type": 12 if private else 11,
            "parent_id": parent["id"],
            "name": name,
            "thread_metadata": {
                "archived": archived,
                "archive_timestamp": when.isoformat(),
                "create_timestamp": when.isoformat(),
            },
        }
        self.threads[thread["id"]] = thread
        for _ in range(messages):
            message = self.add_message(channel_name, f"in {name}", age=age)
            self.messages[parent["id"]].remove(message)
            message["channel_id"] = thread["id"]
            self.messages.setdefault(thread["id"], []).append(message)
        return thread

    def role_named(self, name: str) -> dict:
        return next(r for r in self.roles.values() if r["name"] == name)

    def add_message(
        self, channel_name: str, content: str, author_id: str | None = None, age: timedelta | None = None
    ) -> dict:
        channel = self.by_name(channel_name)
        when = datetime.now(UTC) - (age or timedelta())
        message = {
            "id": snowflake(),
            "channel_id": channel["id"],
            "type": 0,
            "author": {"id": author_id or self.bot_user_id},
            "content": content,
            "flags": 0,
            "embeds": [],
            "attachments": [],
            "pinned": False,
            "timestamp": when.isoformat(),
        }
        self.messages.setdefault(channel["id"], []).append(message)
        return message

    def state(self) -> dict:
        """A copy of everything a run can change, for comparing before and after."""
        return copy.deepcopy(
            {
                "guild": self.guild,
                "roles": self.roles,
                "channels": self.channels,
                "automod": self.automod,
                "webhooks": {k: dict(v) for k, v in self.webhooks.items()},
                "commands": self.commands,
                "onboarding": self.onboarding,
                "messages": self.messages,
                "app": self.app,
            }
        )

    # permission arithmetic, written for this file ----------------------------------------------

    def _is_owner(self, user_id: str) -> bool:
        return user_id == self.owner_id

    def base_for(self, role_ids: list[str], user_id: str | None = None) -> int:
        if user_id and self._is_owner(user_id):
            return ALL
        value = int(self.roles[self.guild_id]["permissions"])
        for rid in role_ids:
            value |= int(self.roles[rid]["permissions"])
        if value & BITS["administrator"]:
            return ALL
        return value

    def in_channel(self, channel: dict, role_ids: list[str], user_id: str | None = None) -> int:
        base = self.base_for(role_ids, user_id)
        if base == ALL:
            return ALL
        value = base
        rows = {o["id"]: o for o in channel.get("permission_overwrites", [])}
        if self.guild_id in rows:
            row = rows[self.guild_id]
            value = (value & ~int(row["deny"])) | int(row["allow"])
        deny = allow = 0
        for rid in role_ids:
            if rid in rows:
                deny |= int(rows[rid]["deny"])
                allow |= int(rows[rid]["allow"])
        value = (value & ~deny) | allow
        if user_id and user_id in rows:
            row = rows[user_id]
            value = (value & ~int(row["deny"])) | int(row["allow"])
        if not value & BITS["view_channel"]:
            return 0
        if channel["type"] in (VOICE, STAGE) and not value & BITS["connect"]:
            # "denying the CONNECT permission also implicitly denies other permissions such as MANAGE_CHANNELS"
            value &= ~BITS["manage_channels"]
        if not value & BITS["send_messages"]:
            value &= ~(
                BITS["send_tts_messages"] | BITS["mention_everyone"] | BITS["embed_links"] | BITS["attach_files"]
            )
        return value

    def perms_for_roles(self, role_names: list[str], channel_name: str | None = None) -> int:
        """What an account holding these roles holds, server wide or in a channel."""
        ids = [self.role_named(n)["id"] for n in role_names]
        if channel_name is None:
            return self.base_for(ids)
        return self.in_channel(self.by_name(channel_name), ids)

    def bot_base(self) -> int:
        return self.base_for(self.bot_member_roles, self.bot_user_id)

    def bot_in(self, channel: dict) -> int:
        return self.in_channel(channel, self.bot_member_roles, self.bot_user_id)

    def bot_top(self) -> int:
        return max(self.roles[r]["position"] for r in self.bot_member_roles)

    def _require(self, have: int, *names: str) -> None:
        for name in names:
            if not have & BITS[name]:
                raise forbidden()

    # request plumbing --------------------------------------------------------------------------

    def fail_next(self, route_contains: str, kind: str = "500", times: int = 1, method: str | None = None) -> None:
        """A regular expression for the path. kind: 500, drop (close before processing) or lost (processed, never answered)."""
        self.faults.append({"match": route_contains, "kind": kind, "times": times, "method": method})

    def limit(self, route: str, limit: int, window: float, bucket: str | None = None) -> None:
        """route such as "POST /guilds/:id/channels". Routes given the same bucket name share it."""
        self.limits[route] = (limit, window, bucket or route)

    def _serve(self, h: BaseHTTPRequestHandler) -> None:
        length = int(h.headers.get("Content-Length") or 0)
        raw = h.rfile.read(length) if length else b""
        parsed = urllib.parse.urlparse(h.path)
        path = parsed.path
        if path.startswith("/api/v10"):
            path = path[len("/api/v10") :]
        query = urllib.parse.parse_qs(parsed.query)
        method = h.command
        with self.lock:
            fault = self._fault(method, path)
            if fault and fault["kind"] == "drop":
                h.connection.close()
                return
            headers: dict = {}
            try:
                self._authenticate(h, raw)
                headers = self._rate_limit(method, path)
                if fault and fault["kind"] == "429":
                    raise Refusal(
                        429,
                        0,
                        "You are being rate limited.",
                        {"Retry-After": "1.000"},
                        {"message": "You are being rate limited.", "retry_after": 1.0, "global": False},
                    )
                if fault and fault["kind"] == "500":
                    # the server fails before doing anything, so nothing is changed
                    raise Refusal(500, 0, "internal error")
                body = self._parse_body(h.headers.get("Content-Type", ""), raw)
                status, payload = self._route(method, path, query, body, h.headers.get("X-Audit-Log-Reason"))
            except Refusal as err:
                status = err.status
                payload = err.body or {"code": err.code, "message": err.message}
                headers = {**headers, **err.headers}
            self.requests.append((method, path, status))
            if method != "GET" and status < 400 and self.after_write:
                self.after_write(self)
        if fault and fault["kind"] == "lost" and status < 400:
            h.connection.close()
            return
        data = json.dumps(payload).encode() if payload is not None else b""
        h.send_response(status)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(data)))
        for key, value in headers.items():
            h.send_header(key, str(value))
        h.end_headers()
        h.wfile.write(data)

    def _fault(self, method: str, path: str) -> dict | None:
        for fault in self.faults:
            if fault["times"] > 0 and re.search(fault["match"], path) and fault["method"] in (None, method):
                fault["times"] -= 1
                return fault
        return None

    def _parse_body(self, content_type: str, raw: bytes):
        """JSON or multipart/form-data with `payload_json` and `files[n]` as the Uploading Files section says."""
        self._files = []
        if not raw:
            return None
        if not content_type.startswith("multipart/form-data"):
            return json.loads(raw)
        boundary = content_type.split("boundary=")[1].encode()
        payload = None
        if len(raw) > 25 * 1024 * 1024:
            raise bad("The maximum request size when sending a message is 25 MiB")
        for part in raw.split(b"--" + boundary)[1:-1]:
            head, _, content = part.strip(b"\r\n").partition(b"\r\n\r\n")
            disposition = head.decode().split("Content-Disposition:")[1].split("\r\n")[0]
            name = re.search(r'name="([^"]+)"', disposition).group(1)
            if name == "payload_json":
                payload = json.loads(content)
                continue
            filename = re.search(r'filename="([^"]+)"', disposition)
            if not re.fullmatch(r"files\[\d+\]", name) or filename is None:
                raise bad("each file must be named files[n] and carry a filename")
            self._files.append((int(name[6:-1]), filename.group(1), content))
        if payload is None:
            raise bad("payload_json is missing")
        return payload

    def _authenticate(self, h, raw: bytes) -> None:
        auth = h.headers.get("Authorization", "")
        if auth != f"Bot {self.token}":
            raise Refusal(401, 0, "401: Unauthorized")
        if not USER_AGENT.match(h.headers.get("User-Agent", "")):
            raise Refusal(403, 40333, "internal network error: a user agent in the documented form is required")
        if raw and h.headers.get("Content-Type", "").split(";")[0] not in ("application/json", "multipart/form-data"):
            raise bad("Content-Type must be application/json")

    @staticmethod
    def _template(path: str) -> str:
        return re.sub(r"/\d{5,}", "/:id", path)

    def _rate_limit(self, method: str, path: str) -> dict:
        now = self.clock.now()
        if self.global_limit:
            limit, window = self.global_limit
            self._global_window = [t for t in self._global_window if now - t < window]
            if len(self._global_window) >= limit:
                self.rejections += 1
                retry = window - (now - self._global_window[0])
                raise Refusal(
                    429,
                    0,
                    "You are being rate limited.",
                    {"Retry-After": f"{retry:.3f}", "X-RateLimit-Global": "true", "X-RateLimit-Scope": "global"},
                    {"message": "You are being rate limited.", "retry_after": retry, "global": True},
                )
            self._global_window.append(now)
        key = f"{method} {self._template(path)}"
        if key not in self.limits:
            return {}
        limit, window, bucket = self.limits[key]
        major = (re.findall(r"\d{5,}", path) or [""])[0]
        stamps = self._windows.setdefault(f"{bucket}:{major}", [])
        stamps[:] = [t for t in stamps if now - t < window]
        if len(stamps) >= limit:
            self.rejections += 1
            retry = window - (now - stamps[0])
            raise Refusal(
                429,
                0,
                "You are being rate limited.",
                {
                    "Retry-After": f"{retry:.3f}",
                    "X-RateLimit-Bucket": bucket,
                    "X-RateLimit-Scope": "user",
                },
                {"message": "You are being rate limited.", "retry_after": retry, "global": False},
            )
        stamps.append(now)
        reset = window - (now - stamps[0])
        return {
            "X-RateLimit-Bucket": bucket,
            "X-RateLimit-Limit": limit,
            "X-RateLimit-Remaining": limit - len(stamps),
            "X-RateLimit-Reset-After": f"{reset:.3f}",
        }

    # routing -----------------------------------------------------------------------------------

    def _route(self, method: str, path: str, query: dict, body, reason: str | None):
        for verb, pattern, handler in self._routes():
            if verb != method:
                continue
            match = re.fullmatch(pattern, path)
            if match:
                if method != "GET":
                    self._check_reason(reason, method, path)
                result = handler(body, query, **match.groupdict())
                if method != "GET":
                    self.write_count += 1
                return result
        raise Refusal(404, 0, "404: Not Found")

    def _check_reason(self, reason: str | None, method: str, path: str) -> None:
        decoded = urllib.parse.unquote(reason) if reason else ""
        if len(decoded) > 512:
            raise bad("X-Audit-Log-Reason is at most 512 characters")
        self.audit.append({"method": method, "route": self._template(path), "reason": decoded})

    def _routes(self):
        g = r"(?P<g>\d+)"
        c = r"(?P<c>\d+)"
        return [
            ("GET", r"/users/@me", self.get_me),
            ("GET", r"/users/@me/guilds", self.get_guilds),
            ("GET", r"/applications/@me", lambda b, q: (200, self.app)),
            ("PATCH", r"/applications/@me", self.patch_app),
            ("GET", rf"/guilds/{g}", self.get_guild),
            ("PATCH", rf"/guilds/{g}", self.patch_guild),
            ("GET", rf"/guilds/{g}/members/(?P<u>\d+)", self.get_member),
            ("GET", rf"/guilds/{g}/roles", self.list_roles),
            ("POST", rf"/guilds/{g}/roles", self.create_role),
            ("PATCH", rf"/guilds/{g}/roles", self.move_roles),
            ("PATCH", rf"/guilds/{g}/roles/(?P<r>\d+)", self.patch_role),
            ("DELETE", rf"/guilds/{g}/roles/(?P<r>\d+)", self.delete_role),
            ("GET", rf"/guilds/{g}/channels", self.list_channels),
            ("POST", rf"/guilds/{g}/channels", self.create_channel),
            ("PATCH", rf"/guilds/{g}/channels", self.move_channels),
            ("GET", rf"/channels/{c}", self.get_channel),
            ("PATCH", rf"/channels/{c}", self.patch_channel),
            ("DELETE", rf"/channels/{c}", self.delete_channel),
            ("GET", rf"/guilds/{g}/auto-moderation/rules", self.list_rules),
            ("POST", rf"/guilds/{g}/auto-moderation/rules", self.create_rule),
            ("PATCH", rf"/guilds/{g}/auto-moderation/rules/(?P<r>\d+)", self.patch_rule),
            ("DELETE", rf"/guilds/{g}/auto-moderation/rules/(?P<r>\d+)", self.delete_rule),
            ("GET", rf"/guilds/{g}/onboarding", self.get_onboarding),
            ("PUT", rf"/guilds/{g}/onboarding", self.put_onboarding),
            ("GET", rf"/guilds/{g}/webhooks", self.list_guild_webhooks),
            ("GET", rf"/channels/{c}/webhooks", self.list_channel_webhooks),
            ("POST", rf"/channels/{c}/webhooks", self.create_webhook),
            ("DELETE", r"/webhooks/(?P<w>\d+)", self.delete_webhook),
            ("GET", rf"/guilds/{g}/threads/active", self.list_active_threads),
            ("GET", rf"/channels/{c}/threads/archived/(?P<kind>public|private)", self.list_archived_threads),
            ("POST", rf"/channels/{c}/threads", self.create_forum_post),
            ("GET", rf"/channels/{c}/messages/(?P<m>\d+)", self.get_message),
            ("GET", rf"/channels/{c}/messages/pins", self.list_pins),
            ("PUT", rf"/channels/{c}/messages/pins/(?P<m>\d+)", self.pin_message),
            ("DELETE", rf"/channels/{c}/messages/pins/(?P<m>\d+)", self.unpin_message),
            ("GET", rf"/channels/{c}/messages", self.list_messages),
            ("POST", rf"/channels/{c}/messages", self.create_message),
            ("PATCH", rf"/channels/{c}/messages/(?P<m>\d+)", self.patch_message),
            ("DELETE", rf"/channels/{c}/messages/(?P<m>\d+)", self.delete_message),
            ("GET", rf"/applications/(?P<a>\d+)/guilds/{g}/commands", self.list_commands),
            ("PUT", rf"/applications/(?P<a>\d+)/guilds/{g}/commands", self.put_commands),
            ("PUT", rf"/guilds/{g}/incident-actions", self.put_incidents),
        ]

    # identity ----------------------------------------------------------------------------------

    def get_me(self, body, query):
        return 200, {"id": self.bot_user_id, "username": "Test Bot", "bot": True}

    def get_guilds(self, body, query):
        mine = [{"id": self.guild_id, "name": self.guild["name"], "owner": False}]
        return 200, mine + [{"id": o["id"], "name": o["name"], "owner": False} for o in self.other_guilds]

    def patch_app(self, body, query):
        for key in body:
            if key != "interactions_endpoint_url":
                raise bad(f"unknown field {key}")
        url = body["interactions_endpoint_url"]
        if url is not None and not str(url).startswith(("https://", "http://127.0.0.1")):
            raise bad("The specified interactions endpoint url could not be verified.", 50035)
        self.app["interactions_endpoint_url"] = url
        return 200, self.app

    def _guild(self, g: str) -> None:
        if g != self.guild_id:
            raise Refusal(404, 10004, "Unknown Guild")

    def get_guild(self, body, query, g):
        self._guild(g)
        data = dict(self.guild)
        data["features"] = list(data["features"])
        if query.get("with_counts") == ["true"]:
            data["approximate_member_count"] = self.member_count
        return 200, data

    def patch_guild(self, body, query, g):
        self._guild(g)
        self._require(self.bot_base(), "manage_guild")
        community = "COMMUNITY" in self.guild["features"]
        for key, value in body.items():
            if key == "verification_level" and value not in range(5):
                raise bad("verification_level must be 0 to 4")
            if key == "explicit_content_filter" and value not in range(3):
                raise bad("explicit_content_filter must be 0 to 2")
            if key == "default_message_notifications" and value not in (0, 1):
                raise bad("default_message_notifications must be 0 or 1")
            if key == "features":
                raise (
                    Refusal(403, 50001, "Enabling or disabling Community requires Administrator")
                    if not self.bot_base() & BITS["administrator"]
                    else bad("not supported")
                )
            if key in ("rules_channel_id", "public_updates_channel_id", "safety_alerts_channel_id"):
                current = self.channels.get(self.guild.get(key) or "")
                if current is not None and not self._visible(current):
                    # seen live: while the server points at a channel the bot cannot see, changing the pointer is refused
                    raise forbidden()
                if not community:
                    raise bad("Community must be enabled to set this channel")
                channel = self.channels.get(value)
                if channel is None or channel["type"] != TEXT:
                    raise bad("must be a text channel")
            if key not in self.guild and key != "system_channel_id":
                raise bad(f"unknown field {key}")
        self.guild.update(body)
        return 200, self.guild

    def get_member(self, body, query, g, u):
        self._guild(g)
        if u != self.bot_user_id:
            raise Refusal(404, 10007, "Unknown Member")
        return 200, {"user": {"id": u}, "roles": list(self.bot_member_roles)}

    # roles -------------------------------------------------------------------------------------

    def list_roles(self, body, query, g):
        self._guild(g)
        return 200, sorted(self.roles.values(), key=lambda r: (r["position"], r["id"]))

    def _held_check(self, bits: int) -> None:
        have = self.bot_base()
        if have & BITS["administrator"]:
            return
        if bits & ~have:
            raise forbidden("A bot can only grant permissions it holds")

    def create_role(self, body, query, g):
        self._guild(g)
        self._require(self.bot_base(), "manage_roles")
        name = body.get("name", "new role")
        if not 1 <= len(name) <= 100:
            raise bad("name must be 1 to 100 characters")
        permissions = int(body.get("permissions", DEFAULT_EVERYONE))
        self._held_check(permissions)
        if len(self.roles) >= 250:
            raise Refusal(400, 30005, "Maximum number of server roles reached")
        if self.new_roles_tie:
            position = max(1, self.bot_top()) if self.bot_member_roles else 1
        else:
            for role in self.roles.values():
                if role["id"] != self.guild_id and role["position"] >= 1:
                    role["position"] += 1
            position = 1
        role = {
            "id": snowflake(),
            "name": name,
            "permissions": str(permissions),
            "position": position,
            "color": int(body.get("color", 0)),
            "hoist": bool(body.get("hoist", False)),
            "managed": False,
            "mentionable": bool(body.get("mentionable", False)),
        }
        self.roles[role["id"]] = role
        self._audit_note("role create")
        return 200, role

    def _audit_note(self, text: str) -> None:
        self.audit[-1]["what"] = text

    def patch_role(self, body, query, g, r):
        self._guild(g)
        self._require(self.bot_base(), "manage_roles")
        role = self.roles.get(r)
        if role is None:
            raise Refusal(404, 10011, "Unknown Role")
        if r != self.guild_id and (role["managed"] or self._not_below_bot(role["position"])):
            raise forbidden("A bot can only edit roles below its own highest role")
        if "permissions" in body:
            added = int(body["permissions"]) & ~int(role["permissions"])
            self._held_check(added)
            role["permissions"] = str(int(body["permissions"]))
        if "name" in body:
            if r == self.guild_id:
                raise bad("@everyone cannot be renamed")
            role["name"] = body["name"]
        for key in ("color", "hoist", "mentionable"):
            if key in body:
                role[key] = body[key]
        return 200, role

    def move_roles(self, body, query, g):
        """Modify Guild Role Positions. The fake treats the places as an order: a moved role is put at its place and
        the roles it passes shift over. How Discord resolves places that clash is not documented (unconfirmed)."""
        self._guild(g)
        self._require(self.bot_base(), "manage_roles")
        for entry in body:
            role = self.roles.get(entry["id"])
            if role is None or self._not_below_bot(role["position"]) or role["managed"] or entry["position"] < 1:
                raise forbidden("A bot can only order roles below its own highest role")
        ordered = sorted(
            (r for r in self.roles.values() if r["id"] != self.guild_id), key=lambda r: (r["position"], r["id"])
        )
        for entry in sorted(body, key=lambda e: e["position"]):
            role = self.roles[entry["id"]]
            ordered.remove(role)
            ordered.insert(min(entry["position"], len(ordered) + 1) - 1, role)
        for place, role in enumerate(ordered, 1):
            role["position"] = place
        return 200, sorted(self.roles.values(), key=lambda r: (r["position"], r["id"]))

    def _not_below_bot(self, position: int) -> bool:
        top = self.bot_top()
        return position >= top if self.ties_block else position > top

    def delete_role(self, body, query, g, r):
        self._guild(g)
        self._require(self.bot_base(), "manage_roles")
        role = self.roles.get(r)
        if role is None:
            raise Refusal(404, 10011, "Unknown Role")
        if role["managed"] or r == self.guild_id or self._not_below_bot(role["position"]):
            raise forbidden("A bot can only delete roles below its own highest role")
        del self.roles[r]
        for channel in self.channels.values():
            channel["permission_overwrites"] = [o for o in channel["permission_overwrites"] if o["id"] != r]
        return 204, None

    # channels ----------------------------------------------------------------------------------

    def _visible(self, channel: dict) -> bool:
        if self.bot_in(channel) & BITS["view_channel"]:
            return True
        if channel["type"] == CATEGORY:
            return any(
                self.bot_in(child) & BITS["view_channel"]
                for child in self.channels.values()
                if child.get("parent_id") == channel["id"]
            )
        return False

    def list_channels(self, body, query, g):
        self._guild(g)
        visible = [c for c in self.channels.values() if self._visible(c)]
        return 200, sorted(visible, key=lambda c: (c["position"], c["id"]))

    def get_channel(self, body, query, c):
        channel = self.channels.get(c)
        if channel is None or not self._visible(channel):
            raise Refusal(404, 10003, "Unknown Channel")
        return 200, channel

    def _allowance(self, parent_id: str | None, creating: bool) -> int:
        """The permissions the bot may name in an overwrite.

        Create Guild Channel: "If setting permission overwrites, only permissions your bot has in the guild can
        be allowed/denied." Modify Channel and Edit Channel Permissions: "Only permissions your bot has in the
        guild or parent channel (if applicable) can be allowed/denied". So when a channel is edited inside a
        category, what the category takes from the bot cannot be named.
        """
        if creating or not parent_id:
            return self.bot_base()
        return self.bot_in(self.channels[parent_id])

    def _check_overwrites(self, rows: list[dict], allowance: int, existing: list[dict] | None = None) -> list[dict]:
        out = []
        have = allowance
        old = {o["id"]: (int(o["allow"]), int(o["deny"])) for o in existing or []}
        for row in rows:
            allow, deny = int(row["allow"]), int(row["deny"])
            if row.get("type") not in (0, 1):
                raise bad("overwrite type must be 0 or 1")
            if row["id"] != self.guild_id and row["id"] not in self.roles and row.get("type") == 0:
                raise bad("overwrite names a role that does not exist")
            touched = allow | deny
            # a row that is already there and unchanged is not being allowed or denied again
            if old.get(row["id"]) != (allow, deny):
                if touched & BITS["manage_roles"] and not self.bot_base() & BITS["administrator"]:
                    raise forbidden("Setting Manage Roles in a channel needs Administrator")
                if not self.bot_base() & BITS["administrator"] and touched & ~have:
                    raise forbidden("An overwrite may only allow or deny permissions the bot holds")
            out.append({"id": row["id"], "type": row["type"], "allow": str(allow), "deny": str(deny)})
        return out

    def _validate_channel_fields(self, kind: int, body: dict, existing: dict | None) -> None:
        name = body.get("name", existing["name"] if existing else None)
        if name is not None and not 1 <= len(name) <= 100:
            raise bad("name must be 1 to 100 characters")
        topic = body.get("topic")
        if topic is not None:
            limit = 4096 if kind == FORUM else 1024
            if kind in (CATEGORY, VOICE):
                raise bad("this channel type has no topic")
            if len(topic) > limit:
                raise bad(f"topic must be {limit} characters or fewer")
        slow = body.get("rate_limit_per_user")
        if slow is not None and not 0 <= slow <= 21600:
            raise bad("rate_limit_per_user must be 0 to 21600")
        slow = body.get("default_thread_rate_limit_per_user")
        if slow is not None and not 0 <= slow <= 21600:
            raise bad("default_thread_rate_limit_per_user must be 0 to 21600")
        tags = body.get("available_tags")
        if tags is not None:
            if kind != FORUM:
                raise bad("only a forum has tags")
            if len(tags) > 20:
                raise bad("a forum holds at most 20 tags")
            for tag in tags:
                if not 1 <= len(tag["name"]) <= 20:
                    raise bad("a tag name is 1 to 20 characters")
        if "default_auto_archive_duration" in body and body["default_auto_archive_duration"] not in (
            60,
            1440,
            4320,
            10080,
        ):
            raise bad("default_auto_archive_duration must be 60, 1440, 4320 or 10080")

    def _needs_community(self, kind: int) -> None:
        features = set(self.guild["features"])
        if kind in (ANNOUNCEMENT, STAGE) and "COMMUNITY" not in features:
            raise bad("This channel type requires the Community feature")
        if kind == ANNOUNCEMENT and "NEWS" not in features:
            raise bad("Guild does not have the NEWS feature")
        if kind == FORUM and self.forums_need_community and "COMMUNITY" not in features:
            raise bad("Forum channels require the Community feature")

    def _make_tags(self, tags: list[dict], existing: list[dict] | None = None) -> list[dict]:
        old = {t["id"]: t for t in existing or []}
        result = []
        for tag in tags:
            kept = old.get(tag.get("id"))
            result.append(
                {
                    "id": tag["id"] if kept else snowflake(),
                    "name": tag["name"],
                    "moderated": bool(tag.get("moderated", False)),
                    "emoji_id": tag.get("emoji_id"),
                    "emoji_name": tag.get("emoji_name"),
                }
            )
        return result

    def create_channel(self, body, query, g):
        self._guild(g)
        self._require(self.bot_base(), "manage_channels")
        kind = body.get("type", TEXT)
        if kind not in VALID_TYPES:
            raise bad("invalid channel type")
        self._needs_community(kind)
        self._validate_channel_fields(kind, body, None)
        parent_id = body.get("parent_id")
        if parent_id is not None:
            parent = self.channels.get(parent_id)
            if parent is None or parent["type"] != CATEGORY:
                raise bad("parent_id must be a category")
            if sum(1 for c in self.channels.values() if c.get("parent_id") == parent_id) >= 50:
                raise bad("a category holds at most 50 channels")
        if kind == CATEGORY and parent_id:
            raise bad("a category cannot have a parent")
        if len(self.channels) >= 500:
            raise bad("a server holds at most 500 channels")
        rows = body.get("permission_overwrites", [])
        if rows:
            self._require(self.bot_base(), "manage_roles")
        name = body["name"]
        if kind in (TEXT, ANNOUNCEMENT, FORUM):
            name = normalise_channel_name(name)
        data = {
            "id": snowflake(),
            "type": kind,
            "name": name,
            "parent_id": parent_id,
            "permission_overwrites": self._check_overwrites(rows, self._allowance(parent_id, True)),
            "topic": body.get("topic"),
            "rate_limit_per_user": body.get("rate_limit_per_user", 0),
            "flags": body.get("flags", 0),
        }
        siblings = [
            c
            for c in self.channels.values()
            if (c["type"] == CATEGORY) == (kind == CATEGORY) and c.get("parent_id") == parent_id
        ]
        data["position"] = (
            body["position"] if "position" in body else max([c["position"] for c in siblings], default=-1) + 1
        )
        if kind == FORUM:
            data["available_tags"] = self._make_tags(body.get("available_tags", []))
            for key in (
                "default_sort_order",
                "default_forum_layout",
                "default_thread_rate_limit_per_user",
                "default_auto_archive_duration",
            ):
                if key in body:
                    data[key] = body[key]
        self.channels[data["id"]] = data
        return 200, data

    def _channel_for_edit(self, c: str) -> dict:
        channel = self.channels.get(c)
        if channel is None or not self._visible(channel):
            raise Refusal(404, 10003, "Unknown Channel")
        self._require(self.bot_in(channel), "manage_channels")
        return channel

    def patch_channel(self, body, query, c):
        thread = self.threads.get(c)
        if thread is not None:
            # changing a thread's flags (the forum PINNED flag) needs Manage Threads on its forum
            self._require(self.bot_in(self.channels[thread["parent_id"]]), "manage_threads")
            body = dict(body)
            if "archived" in body:
                thread["thread_metadata"]["archived"] = bool(body.pop("archived"))
                if thread["thread_metadata"]["archived"]:
                    # "Archiving a pinned forum post unsets the PINNED flag"
                    thread["flags"] = thread.get("flags", 0) & ~2
            if (body.get("flags", 0) & 2) and not thread.get("flags", 0) & 2:
                others = [
                    t
                    for t in self.threads.values()
                    if t["parent_id"] == thread["parent_id"] and t["id"] != c and t.get("flags", 0) & 2
                ]
                if others:
                    raise Refusal(400, 30047, "Maximum number of pinned threads reached: one post is pinned per forum")
            for key, value in body.items():
                thread[key] = value
            return 200, thread
        channel = self._channel_for_edit(c)
        if "type" in body and body["type"] != channel["type"]:
            if {body["type"], channel["type"]} != {TEXT, ANNOUNCEMENT}:
                raise bad("Only text and announcement channels convert into each other")
            self._needs_community(body["type"])
        self._validate_channel_fields(body.get("type", channel["type"]), body, channel)
        if "parent_id" in body and body["parent_id"] is not None:
            parent = self.channels.get(body["parent_id"])
            if parent is None or parent["type"] != CATEGORY:
                raise bad("parent_id must be a category")
            self._require(self.bot_in(parent), "manage_channels")
            if sum(1 for x in self.channels.values() if x.get("parent_id") == body["parent_id"] and x["id"] != c) >= 50:
                raise bad("a category holds at most 50 channels")
        if "permission_overwrites" in body:
            self._require(self.bot_in(channel), "manage_roles")
            parent = body["parent_id"] if "parent_id" in body else channel.get("parent_id")
            channel["permission_overwrites"] = self._check_overwrites(
                body["permission_overwrites"], self._allowance(parent, False), channel["permission_overwrites"]
            )
        for key, value in body.items():
            if key == "permission_overwrites":
                continue
            if key == "available_tags":
                channel["available_tags"] = self._make_tags(value, channel.get("available_tags"))
            elif key == "name":
                channel["name"] = (
                    normalise_channel_name(value) if channel["type"] in (TEXT, ANNOUNCEMENT, FORUM) else value
                )
            else:
                channel[key] = value
        return 200, channel

    def move_channels(self, body, query, g):
        self._guild(g)
        self._require(self.bot_base(), "manage_channels")
        for entry in body:
            if entry["id"] not in self.channels:
                raise bad("unknown channel")
        # "At most one entry per request may change parent_id." (Modify Guild Channel Positions)
        moving = [e for e in body if "parent_id" in e and e["parent_id"] != self.channels[e["id"]].get("parent_id")]
        if len(moving) > 1:
            raise Refusal(400, 40009, "A request may change the parent of at most one channel")
        for entry in body:
            channel = self.channels[entry["id"]]
            parent = self.channels.get(channel.get("parent_id") or "")
            # position-only entries need Manage Channels at the guild level or on the channel's current parent
            if not (
                self.bot_base() & BITS["manage_channels"] or (parent and self.bot_in(parent) & BITS["manage_channels"])
            ):
                raise forbidden()
        for entry in body:
            self.channels[entry["id"]]["position"] = entry["position"]
        return 204, None

    def delete_channel(self, body, query, c):
        thread = self.threads.get(c)
        if thread is not None:
            # "Requires the MANAGE_CHANNELS permission for the guild or MANAGE_THREADS if the channel is a thread."
            self._require(self.bot_in(self.channels[thread["parent_id"]]), "manage_threads")
            del self.threads[c]
            self.messages.pop(c, None)
            return 200, thread
        channel = self._channel_for_edit(c)
        community = "COMMUNITY" in self.guild["features"]
        if community and c in (self.guild["rules_channel_id"], self.guild["public_updates_channel_id"]):
            raise Refusal(400, 50074, "Cannot delete a channel required for Community servers")
        del self.channels[c]
        for child in self.channels.values():
            if child.get("parent_id") == channel["id"]:
                child["parent_id"] = None
        return 200, channel

    # auto moderation ---------------------------------------------------------------------------

    def list_rules(self, body, query, g):
        self._guild(g)
        self._require(self.bot_base(), "manage_guild")
        return 200, list(self.automod.values())

    LIMITS = {1: 6, 3: 1, 4: 1, 5: 1, 6: 1}

    def _check_rule(self, body: dict, existing: dict | None) -> dict:
        trigger = body.get("trigger_type", existing["trigger_type"] if existing else None)
        if trigger not in self.LIMITS:
            raise bad("invalid trigger type")
        meta = body.get("trigger_metadata", existing["trigger_metadata"] if existing else {})
        actions = body.get("actions", existing["actions"] if existing else [])
        if not actions:
            raise bad("at least one action is required")
        keywords = meta.get("keyword_filter", [])
        if len(keywords) > 1000 or any(len(k) > 60 for k in keywords):
            raise bad("keywords are at most 60 characters")
        patterns = meta.get("regex_patterns", [])
        if len(patterns) > 10 or any(len(p) > 260 for p in patterns):
            raise bad("at most 10 patterns of 260 characters")
        for action in actions:
            meta_a = action.get("metadata") or {}
            if action["type"] == 3:
                if trigger not in (1, 5):
                    raise bad("A timeout action can only be set up for keyword and mention spam rules")
                self._require(self.bot_base(), "moderate_members")
                if not 1 <= meta_a.get("duration_seconds", 0) <= 2419200:
                    raise bad("duration_seconds must be 1 to 2419200")
            if action["type"] == 2 and meta_a.get("channel_id") not in self.channels:
                raise bad("alert channel does not exist")
            if len(meta_a.get("custom_message", "")) > 150:
                raise bad("custom_message is at most 150 characters")
            if action["type"] not in (1, 2, 3, 4):
                raise bad("invalid action type")
        for rid in body.get("exempt_roles", []):
            if rid not in self.roles:
                raise bad("exempt role does not exist")
        if len(body.get("exempt_roles", [])) > 20:
            raise bad("at most 20 exempt roles")
        return {"trigger_type": trigger}

    def create_rule(self, body, query, g):
        self._guild(g)
        self._require(self.bot_base(), "manage_guild")
        info = self._check_rule(body, None)
        same = sum(1 for r in self.automod.values() if r["trigger_type"] == info["trigger_type"])
        if same >= self.LIMITS[info["trigger_type"]]:
            raise Refusal(400, 200000, "Maximum number of rules of this trigger type reached")
        rule = {
            "id": snowflake(),
            "guild_id": g,
            "name": body["name"],
            "event_type": body.get("event_type", 1),
            "trigger_type": body["trigger_type"],
            "trigger_metadata": body.get("trigger_metadata", {}),
            "actions": body["actions"],
            "enabled": body.get("enabled", True),
            "exempt_roles": body.get("exempt_roles", []),
            "exempt_channels": body.get("exempt_channels", []),
        }
        self.automod[rule["id"]] = rule
        return 200, rule

    def patch_rule(self, body, query, g, r):
        self._guild(g)
        self._require(self.bot_base(), "manage_guild")
        rule = self.automod.get(r)
        if rule is None:
            raise Refusal(404, 10020, "Unknown Auto Moderation Rule")
        if "trigger_type" in body:
            raise bad("trigger_type cannot be changed")
        self._check_rule(body, rule)
        rule.update(body)
        return 200, rule

    def delete_rule(self, body, query, g, r):
        self._guild(g)
        self._require(self.bot_base(), "manage_guild")
        if r not in self.automod:
            raise Refusal(404, 10020, "Unknown Auto Moderation Rule")
        del self.automod[r]
        return 204, None

    # onboarding --------------------------------------------------------------------------------

    def get_onboarding(self, body, query, g):
        self._guild(g)
        self._require(self.bot_base(), "manage_guild")
        return 200, {"guild_id": g, **self.onboarding}

    def put_onboarding(self, body, query, g):
        self._guild(g)
        self._require(self.bot_base(), "manage_guild")
        self._require(self.bot_base(), "manage_roles")
        if "COMMUNITY" not in self.guild["features"]:
            raise Refusal(403, 50001, "Onboarding requires Community")
        defaults = body.get("default_channel_ids", [])
        for cid in defaults:
            channel = self.channels.get(cid)
            if channel is None or channel["type"] not in (TEXT, ANNOUNCEMENT, FORUM):
                raise bad("default channel must be a text, announcement or forum channel")
        prompts = []
        for prompt in body.get("prompts", []):
            if not 1 <= len(prompt["title"]) <= 100:
                raise bad("prompt title is 1 to 100 characters")
            options = []
            for option in prompt["options"]:
                if not 1 <= len(option["title"]) <= 50:
                    raise bad("option title is 1 to 50 characters")
                for rid in option.get("role_ids", []):
                    if rid not in self.roles:
                        raise bad("option names a role that does not exist")
                for cid in option.get("channel_ids", []):
                    if cid not in self.channels:
                        raise bad("option names a channel that does not exist")
                options.append(
                    {
                        "id": option.get("id") or snowflake(),
                        "title": option["title"],
                        "description": option.get("description"),
                        "role_ids": option.get("role_ids", []),
                        "channel_ids": option.get("channel_ids", []),
                    }
                )
            prompts.append(
                {
                    "id": prompt.get("id") or snowflake(),
                    "type": prompt["type"],
                    "title": prompt["title"],
                    "single_select": prompt.get("single_select", False),
                    "required": prompt.get("required", False),
                    "in_onboarding": prompt.get("in_onboarding", True),
                    "options": options,
                }
            )
        enabled = bool(body.get("enabled", False))
        # the first live apply was refused with 400 Invalid Form Body while onboarding was still off, so the minimums
        # are taken to apply whenever default channels are sent
        if enabled or defaults:
            postable = 0
            for cid in defaults:
                channel = self.channels[cid]
                if channel["type"] == FORUM and not self.forums_count_for_onboarding:
                    continue
                if self.in_channel(channel, []) & BITS["send_messages"]:
                    postable += 1
            if len(defaults) < 7 or postable < self.onboarding_needs_postable:
                text = (
                    "There must be at least 7 Default Channels and at least 5 of them must allow sending messages "
                    "to the @everyone role"
                )
                raise Refusal(
                    400,
                    50035,
                    "Invalid Form Body",
                    body={
                        "code": 50035,
                        "message": "Invalid Form Body",
                        "errors": {
                            "default_channel_ids": {"_errors": [{"code": "ONBOARDING_CONSTRAINTS", "message": text}]}
                        },
                    },
                )
        self.onboarding = {
            "prompts": prompts,
            "default_channel_ids": defaults,
            "enabled": enabled,
            "mode": body.get("mode", 0),
        }
        return 200, {"guild_id": g, **self.onboarding}

    # webhooks ----------------------------------------------------------------------------------

    def _webhook_view(self, hook: dict) -> dict:
        return hook

    def list_guild_webhooks(self, body, query, g):
        self._guild(g)
        self._require(self.bot_base(), "manage_webhooks")
        return 200, list(self.webhooks.values())

    def list_channel_webhooks(self, body, query, c):
        channel = self._channel_for_edit_webhooks(c)
        return 200, [h for h in self.webhooks.values() if h["channel_id"] == channel["id"]]

    def _channel_for_edit_webhooks(self, c: str) -> dict:
        channel = self.channels.get(c)
        if channel is None or not self._visible(channel):
            raise Refusal(404, 10003, "Unknown Channel")
        self._require(self.bot_base(), "manage_webhooks")
        return channel

    def create_webhook(self, body, query, c):
        channel = self._channel_for_edit_webhooks(c)
        name = body.get("name", "")
        if not 1 <= len(name) <= 80:
            raise bad("webhook name is 1 to 80 characters")
        if "discord" in name.lower() or "clyde" in name.lower():
            raise bad("Webhook names cannot contain 'discord' or 'clyde'")
        if sum(1 for h in self.webhooks.values() if h["channel_id"] == c) >= 15:
            raise Refusal(400, 30007, "Maximum number of webhooks reached (15)")
        hook_id = snowflake()
        token = "tok" + snowflake()[-8:]
        hook = {
            "id": hook_id,
            "type": 1,
            "guild_id": self.guild_id,
            "channel_id": channel["id"],
            "name": name,
            "application_id": self.app_id,
            "token": token,
            "url": f"http://127.0.0.1/hooks/{hook_id}/{token}",
        }
        self.webhooks[hook_id] = hook
        return 200, hook

    def delete_webhook(self, body, query, w):
        self._require(self.bot_base(), "manage_webhooks")
        if w not in self.webhooks:
            raise Refusal(404, 10015, "Unknown Webhook")
        del self.webhooks[w]
        return 204, None

    # messages ----------------------------------------------------------------------------------

    def _message_channel(self, c: str, *needs: str) -> dict:
        thread = self.threads.get(c)
        if thread is not None:
            # a thread follows the permissions of the channel it belongs to
            parent = self.channels[thread["parent_id"]]
            if not self._visible(parent):
                raise Refusal(404, 10003, "Unknown Channel")
            self._require(self.bot_in(parent), *needs)
            return {**parent, "id": c}
        channel = self.channels.get(c)
        if channel is None or not self._visible(channel):
            raise Refusal(404, 10003, "Unknown Channel")
        have = self.bot_in(channel)
        self._require(have, *needs)
        return channel

    def list_messages(self, body, query, c):
        channel = self._message_channel(c, "view_channel", "read_message_history")
        items = sorted(self.messages.get(channel["id"], []), key=lambda m: int(m["id"]), reverse=True)
        before = query.get("before", [None])[0]
        if before:
            items = [m for m in items if int(m["id"]) < int(before)]
        return 200, items[: int(query.get("limit", ["50"])[0])]

    def list_active_threads(self, body, query, g):
        self._guild(g)
        mine = [t for t in self.threads.values() if not t["thread_metadata"]["archived"]]
        return 200, {"threads": sorted(mine, key=lambda t: int(t["id"]), reverse=True), "members": []}

    def list_archived_threads(self, body, query, c, kind):
        channel = self.channels.get(c)
        if channel is None or not self._visible(channel):
            raise Refusal(404, 10003, "Unknown Channel")
        have = self.bot_in(channel)
        self._require(have, "read_message_history")
        if kind == "private":
            self._require(have, "manage_threads")
        wanted = 12 if kind == "private" else 11
        mine = [
            t
            for t in self.threads.values()
            if t["parent_id"] == c and t["thread_metadata"]["archived"] and t["type"] == wanted
        ]
        mine.sort(key=lambda t: t["thread_metadata"]["archive_timestamp"], reverse=True)
        before = query.get("before", [None])[0]
        if before:
            mine = [t for t in mine if t["thread_metadata"]["archive_timestamp"] < before]
        limit = int(query.get("limit", ["50"])[0])
        return 200, {"threads": mine[:limit], "members": [], "has_more": len(mine) > limit}

    ALLOWED_UPLOADS = (".jpg", ".jpeg", ".png", ".webp", ".gif")

    def _message_body(self, body: dict) -> dict:
        content = body.get("content", "") or ""
        if len(content) > 2000:
            raise bad("content must be 2000 characters or fewer")
        embeds = body.get("embeds", []) or []
        if len(embeds) > 10:
            raise bad("a message holds at most 10 embeds")
        total = 0
        for embed in embeds:
            title, description = embed.get("title", ""), embed.get("description", "")
            if len(title) > 256:
                raise bad("embed title is 256 characters at most")
            if len(description) > 4096:
                raise bad("embed description is 4096 characters at most")
            if len(embed.get("fields", [])) > 25:
                raise bad("an embed holds at most 25 fields")
            total += len(title) + len(description)
            for fld in embed.get("fields", []):
                if len(fld["name"]) > 256 or len(fld["value"]) > 1024:
                    raise bad("a field name is 256 characters and a value 1024 at most")
                total += len(fld["name"]) + len(fld["value"])
            total += len(embed.get("footer", {}).get("text", "")) + len(embed.get("author", {}).get("name", ""))
        if total > 6000:
            raise bad("all the text of the embeds of one message may not pass 6000 characters")
        mentions = body.get("allowed_mentions")
        return {"content": content, "flags": body.get("flags", 0), "embeds": embeds, "allowed_mentions": mentions}

    def _attachments(self, channel_id: str, body: dict, existing: list[dict] | None) -> list[dict]:
        """New files are appended. On an edit "the attachments array must contain all attachments that should be
        present after edit" (the message page), so an old one not listed is dropped."""
        listed = body.get("attachments")
        kept = []
        if existing is not None and listed is not None:
            ids = {str(x["id"]) for x in listed if not isinstance(x["id"], int)}
            kept = [dict(a) for a in existing if a["id"] in ids]
            for row in kept:
                said = next((x for x in listed if str(x["id"]) == row["id"] and "description" in x), None)
                if said:
                    row["description"] = said["description"]
        elif existing is not None:
            kept = list(existing)
        new = []
        for index, filename, content in self._files:
            if not filename.lower().endswith(self.ALLOWED_UPLOADS):
                raise bad("only .jpg, .jpeg, .png, .webp and .gif may be used at this time")
            if listed is not None and index not in {x["id"] for x in listed if isinstance(x["id"], int)}:
                continue
            attachment_id = snowflake()
            wanted = next((x for x in listed or [] if x["id"] == index), {})
            new.append(
                {
                    "id": attachment_id,
                    "filename": filename,
                    **({"description": wanted["description"]} if wanted.get("description") else {}),
                    "size": len(content),
                    "url": f"https://cdn.fake.invalid/attachments/{channel_id}/{attachment_id}/{filename}",
                    "sha256": __import__("hashlib").sha256(content).hexdigest(),
                }
            )
        return kept + new

    def _resolve_embed_images(self, embeds: list[dict], attachments: list[dict]) -> list[dict]:
        out = []
        for embed in embeds:
            embed = json.loads(json.dumps(embed))
            for key in ("thumbnail", "image"):
                url = (embed.get(key) or {}).get("url", "")
                if url.startswith("attachment://"):
                    name = url[len("attachment://") :]
                    found = next((a for a in attachments if a["filename"] == name), None)
                    if found is None:
                        raise bad(f"the embed refers to attachment://{name}, which was not uploaded")
                    embed[key]["url"] = found["url"]
                    if self.discord_like_embed_files:
                        embed[key]["url"] += "?ex=66f00000&is=66ef0000&hm=" + "ab" * 32 + "&"
                        embed[key]["proxy_url"] = found["url"].replace("cdn.fake.invalid", "media.fake.invalid")
                        embed[key]["width"], embed[key]["height"] = 512, 512
            out.append(embed)
        return out

    def create_message(self, body, query, c):
        channel = self._message_channel(c, "view_channel", "send_messages")
        if channel["type"] in (CATEGORY, FORUM):
            raise bad("cannot send messages in this channel")
        data = self._message_body(body)
        attachments = self._attachments(c, body, None)
        if not data["content"] and not data["embeds"] and not attachments:
            raise bad("Cannot send an empty message")
        data["embeds"] = self._resolve_embed_images(data["embeds"], attachments)
        message = {
            "id": snowflake(),
            "channel_id": c,
            "type": 0,
            "author": {"id": self.bot_user_id},
            "timestamp": datetime.now(UTC).isoformat(),
            "attachments": [] if self.discord_like_embed_files and data["embeds"] else attachments,
            "pinned": False,
            **data,
        }
        self.messages.setdefault(c, []).append(message)
        return 200, message

    def patch_message(self, body, query, c, m):
        self._message_channel(c, "view_channel")
        message = next((x for x in self.messages.get(c, []) if x["id"] == m), None)
        if message is None:
            raise Refusal(404, 10008, "Unknown Message")
        if message["author"]["id"] != self.bot_user_id:
            raise Refusal(403, 50005, "Cannot edit a message authored by another user")
        thread = self.threads.get(c)
        if thread is not None and thread["thread_metadata"]["archived"] and self.archived_threads_immutable:
            raise Refusal(400, 50083, "Thread is archived")
        merged = {**{k: message[k] for k in ("content", "flags", "embeds")}, **body}
        data = self._message_body(merged)
        attachments = self._attachments(c, body, message.get("attachments", []))
        data["embeds"] = self._resolve_embed_images(data["embeds"], attachments)
        if not data["content"] and not data["embeds"] and not attachments:
            raise bad("Cannot send an empty message")
        message.update(data)
        message["attachments"] = [] if self.discord_like_embed_files and data["embeds"] else attachments
        message["edited_timestamp"] = datetime.now(UTC).isoformat()
        return 200, message

    # forum posts -------------------------------------------------------------------------------

    def create_forum_post(self, body, query, c):
        """Start Thread in Forum Channel: a post with its first message, tags and the PINNED flag later."""
        forum = self.channels.get(c)
        if forum is None or not self._visible(forum) or forum["type"] != FORUM:
            raise Refusal(404, 10003, "Unknown Channel")
        have = self.bot_in(forum)
        if not 1 <= len(body.get("name", "")) <= 100:
            raise bad("name must be 1 to 100 characters")
        tags = body.get("applied_tags", [])
        known = {t["id"]: t for t in forum.get("available_tags", [])}
        if len(tags) > 5 or any(t not in known for t in tags):
            raise bad("applied_tags names a tag the forum does not have or more than five")
        if forum["flags"] & (1 << 4) and not tags:
            raise bad("this forum requires a tag on every post")
        if any(known[t].get("moderated") for t in tags):
            # "A moderated tag can only be set by a member with Manage Threads"
            self._require(have, "manage_threads")
        message = self._message_body(body["message"])
        message.pop("allowed_mentions", None)
        thread_id = snowflake()
        thread = {
            "id": thread_id,
            "type": 11,
            "parent_id": c,
            "owner_id": self.bot_user_id,
            "name": body["name"],
            "flags": 0,
            "applied_tags": tags,
            "thread_metadata": {
                "archived": False,
                "archive_timestamp": datetime.now(UTC).isoformat(),
                "create_timestamp": datetime.now(UTC).isoformat(),
            },
        }
        self.threads[thread_id] = thread
        starter = {
            "id": thread_id,
            "channel_id": thread_id,
            "type": 0,
            "author": {"id": self.bot_user_id},
            "timestamp": datetime.now(UTC).isoformat(),
            "attachments": [],
            "pinned": False,
            "allowed_mentions": body["message"].get("allowed_mentions"),
            **message,
        }
        self.messages[thread_id] = [starter]
        return 201, {**thread, "message": starter}

    def get_message(self, body, query, c, m):
        self._message_channel(c, "view_channel", "read_message_history")
        return 200, self._message_in(c, m)

    # pins --------------------------------------------------------------------------------------

    MAX_PINS = 50

    def _message_in(self, c: str, m: str) -> dict:
        message = next((x for x in self.messages.get(c, []) if x["id"] == m), None)
        if message is None:
            raise Refusal(404, 10008, "Unknown Message")
        return message

    def pin_message(self, body, query, c, m):
        """Pin Message: "Requires the PIN_MESSAGES permission". The pin leaves a notice, message type 6."""
        self._message_channel(c, "view_channel", "pin_messages")
        message = self._message_in(c, m)
        if message.get("pinned"):
            return 204, None
        if sum(1 for x in self.messages.get(c, []) if x.get("pinned")) >= self.MAX_PINS:
            raise Refusal(400, 30003, "Maximum number of pins reached for the channel (50)")
        self._pin_clock = getattr(self, "_pin_clock", 0) + 1
        message["pinned"] = True
        message["pinned_at"] = (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=self._pin_clock)).isoformat()
        self.messages[c].append(
            {
                "id": snowflake(),
                "channel_id": c,
                "type": 6,
                "author": {"id": self.bot_user_id},
                "timestamp": datetime.now(UTC).isoformat(),
                "content": "",
                "flags": 0,
                "embeds": [],
                "attachments": [],
                "message_reference": {"message_id": m, "channel_id": c},
            }
        )
        return 204, None

    def unpin_message(self, body, query, c, m):
        self._message_channel(c, "view_channel", "pin_messages")
        message = self._message_in(c, m)
        message["pinned"] = False
        message.pop("pinned_at", None)
        return 204, None

    def list_pins(self, body, query, c):
        """Get Channel Pins needs View Channel and without Read Message History no pins are returned."""
        channel = self._message_channel(c, "view_channel")
        if not self.bot_in(channel) & BITS["read_message_history"]:
            return 200, {"items": [], "has_more": False}
        pinned = [x for x in self.messages.get(c, []) if x.get("pinned")]
        pinned.sort(key=lambda x: x["pinned_at"], reverse=self.pins_newest_first)
        before = query.get("before", [None])[0]
        if before:
            pinned = [x for x in pinned if x["pinned_at"] < before]
        limit = int(query.get("limit", ["50"])[0])
        items = [{"pinned_at": x["pinned_at"], "message": x} for x in pinned[:limit]]
        return 200, {"items": items, "has_more": len(pinned) > limit}

    def delete_message(self, body, query, c, m):
        thread = self.threads.get(c)
        if thread is not None and thread["thread_metadata"]["archived"] and self.archived_threads_immutable:
            raise Refusal(400, 50083, "Thread is archived")
        channel = self._message_channel(c, "view_channel")
        message = next((x for x in self.messages.get(c, []) if x["id"] == m), None)
        if message is None:
            raise Refusal(404, 10008, "Unknown Message")
        if message["author"]["id"] != self.bot_user_id:
            self._require(self.bot_in(channel), "manage_messages")
        self.messages[c].remove(message)
        return 204, None

    # commands and incidents --------------------------------------------------------------------

    def list_commands(self, body, query, a, g):
        self._guild(g)
        return 200, self.commands

    def put_commands(self, body, query, a, g):
        self._guild(g)
        if a != self.app_id:
            raise Refusal(404, 10002, "Unknown Application")
        if len(body) > 100:
            raise bad("at most 100 commands")
        names = set()
        stored = []
        for command in body:
            kind = command.get("type", 1)
            name = command["name"]
            if (name, kind) in names:
                raise bad("duplicate command name")
            names.add((name, kind))
            if kind == 1:
                if not re.fullmatch(r"[a-z0-9_-]{1,32}", name):
                    raise bad("command names are lower case, 1 to 32 characters")
                if not 1 <= len(command.get("description", "")) <= 100:
                    raise bad("description is 1 to 100 characters")
            elif command.get("description"):
                raise bad("a message command has no description")
            self._check_options(command.get("options", []), 0)
            # a command that keeps its name and kind keeps its id, so a link to it in a message stays valid
            keep = next((x["id"] for x in self.commands if (x["name"], x.get("type", 1)) == (name, kind)), None)
            stored.append(
                {**command, "id": keep or snowflake(), "application_id": a, "guild_id": g, "version": snowflake()}
            )
        self.commands = stored
        return 200, stored

    def _check_options(self, options: list[dict], depth: int) -> None:
        if len(options) > 25:
            raise bad("at most 25 options")
        seen_optional = False
        for option in options:
            if option.get("required") and seen_optional:
                raise bad("required options must come first")
            if not option.get("required"):
                seen_optional = True
            if not 1 <= len(option.get("description", "")) <= 100:
                raise bad("option description is 1 to 100 characters")
            if len(option.get("choices", [])) > 25:
                raise bad("at most 25 choices")
            self._check_options(option.get("options", []), depth + 1)

    def put_incidents(self, body, query, g):
        self._guild(g)
        self._require(self.bot_base(), "manage_guild")
        limit = self.clock_utc() + timedelta(hours=24, seconds=5)
        for key in ("invites_disabled_until", "dms_disabled_until"):
            value = body.get(key)
            if value is not None and datetime.fromisoformat(value) > limit:
                raise bad("an incident action lasts at most 24 hours")
        self.guild["incidents_data"] = {
            "invites_disabled_until": body.get("invites_disabled_until"),
            "dms_disabled_until": body.get("dms_disabled_until"),
        }
        return 200, self.guild

    @staticmethod
    def clock_utc() -> datetime:
        return datetime.now(UTC)
