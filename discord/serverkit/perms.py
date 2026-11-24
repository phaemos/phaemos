"""Discord permission bits and the documented resolution order.

The same arithmetic is used to compute what each kind of account can do in each channel, so a layout
that would lock someone out or leak a staff channel fails before anything is sent.
"""

from __future__ import annotations

PERMISSION_BITS: dict[str, int] = {
    "create_instant_invite": 0,
    "kick_members": 1,
    "ban_members": 2,
    "administrator": 3,
    "manage_channels": 4,
    "manage_guild": 5,
    "add_reactions": 6,
    "view_audit_log": 7,
    "priority_speaker": 8,
    "stream": 9,
    "view_channel": 10,
    "send_messages": 11,
    "send_tts_messages": 12,
    "manage_messages": 13,
    "embed_links": 14,
    "attach_files": 15,
    "read_message_history": 16,
    "mention_everyone": 17,
    "use_external_emojis": 18,
    "view_guild_insights": 19,
    "connect": 20,
    "speak": 21,
    "mute_members": 22,
    "deafen_members": 23,
    "move_members": 24,
    "use_vad": 25,
    "change_nickname": 26,
    "manage_nicknames": 27,
    "manage_roles": 28,
    "manage_webhooks": 29,
    "manage_guild_expressions": 30,
    "use_application_commands": 31,
    "request_to_speak": 32,
    "manage_events": 33,
    "manage_threads": 34,
    "create_public_threads": 35,
    "create_private_threads": 36,
    "use_external_stickers": 37,
    "send_messages_in_threads": 38,
    "use_embedded_activities": 39,
    "moderate_members": 40,
    "view_creator_monetization_analytics": 41,
    "use_soundboard": 42,
    "create_guild_expressions": 43,
    "create_events": 44,
    "use_external_sounds": 45,
    "send_voice_messages": 46,
    "set_voice_channel_status": 48,
    "send_polls": 49,
    "use_external_apps": 50,
    "pin_messages": 51,
    "bypass_slowmode": 52,
}

BIT: dict[str, int] = {name: 1 << shift for name, shift in PERMISSION_BITS.items()}
ALL_PERMISSIONS = sum(BIT.values())

# no role a person holds and no overwrite, may carry one of these. Only the bot and the owner change
# the shape of the server.
STRUCTURAL = ("administrator", "manage_guild", "manage_roles", "manage_channels", "manage_webhooks")
STRUCTURAL_MASK = sum(BIT[name] for name in STRUCTURAL)

# permissions the bot never holds. The owner sets them on a role by hand, once and the script only checks
# them. A stolen token can then neither kick, ban nor ping everyone
OWNER_ONLY = ("kick_members", "ban_members", "mention_everyone")
OWNER_ONLY_MASK = sum(BIT[name] for name in OWNER_ONLY)

# the permissions the script needs for its own work, whatever the layout says
BASE_BOT_PERMISSIONS = (
    "view_channel",
    "manage_channels",
    "manage_roles",
    "manage_guild",
    "manage_webhooks",
    "send_messages",
    "read_message_history",
    "moderate_members",
    "manage_messages",
    "manage_threads",
    # pinning was split from Manage Messages: "Requires the PIN_MESSAGES permission" (Pin Message, Unpin Message)
    "pin_messages",
)


class UnknownPermission(ValueError):
    pass


def to_int(names: list[str] | tuple[str, ...]) -> int:
    value = 0
    for name in names:
        if name not in BIT:
            raise UnknownPermission(name)
        value |= BIT[name]
    return value


def names_of(value: int) -> list[str]:
    return [name for name, bit in BIT.items() if value & bit]


def has(value: int, name: str) -> bool:
    return bool(value & BIT[name])


def apply_implicit(value: int, voice: bool = False) -> int:
    """Permissions that cannot work without another one.

    Without View Channel nothing else counts in the channel. Without Send Messages the four that
    ride on a message are lost as well. In a voice or stage channel, denying Connect also takes away
    others such as Manage Channels (the permissions page: "denying the CONNECT permission also implicitly
    denies other permissions such as MANAGE_CHANNELS").
    """
    if not value & BIT["view_channel"]:
        return 0
    if voice and not value & BIT["connect"]:
        value &= ~BIT["manage_channels"]
    if not value & BIT["send_messages"]:
        value &= ~(BIT["send_tts_messages"] | BIT["mention_everyone"] | BIT["embed_links"] | BIT["attach_files"])
    return value


def base_permissions(everyone: int, role_permissions: list[int]) -> int:
    value = everyone
    for extra in role_permissions:
        value |= extra
    if value & BIT["administrator"]:
        return ALL_PERMISSIONS
    return value


def channel_permissions(
    base: int,
    everyone_overwrite: tuple[int, int] | None,
    role_overwrites: list[tuple[int, int]],
    voice: bool = False,
) -> int:
    """Apply a channel's overwrites in Discord's fixed order.

    Everyone first, then every role deny together, then every role allow together.
    """
    if base & BIT["administrator"]:
        return ALL_PERMISSIONS
    value = base
    if everyone_overwrite:
        allow, deny = everyone_overwrite
        value = (value & ~deny) | allow
    denies = 0
    allows = 0
    for allow, deny in role_overwrites:
        denies |= deny
        allows |= allow
    value = (value & ~denies) | allows
    return apply_implicit(value, voice)


def required_for_bot(everything: list[int]) -> int:
    """The bot must hold every permission it may grant, plus the base set and never an owner only one."""
    value = to_int(BASE_BOT_PERMISSIONS)
    for item in everything:
        value |= item
    return value & ~OWNER_ONLY_MASK
