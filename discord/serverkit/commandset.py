"""Turns the command content file into the commands Discord is told about."""

from __future__ import annotations

import json

CHAT_INPUT, MESSAGE = 1, 3
OPTION_TYPES = {"subcommand": 1, "string": 3, "integer": 4, "boolean": 5, "user": 6}
STAFF_PERMISSION = "8192"
MAX_COMMANDS = 100
SHARE_DESCRIPTION = "Show the answer to everyone in the channel"


def _choices(option: dict, content: dict, where: str, errors: list[str]) -> list[dict]:
    source = option.get("choices_from")
    if source is None and "choices" in option:
        return [{"name": str(v), "value": v} for v in option["choices"]]
    if source is None:
        return []
    items = content.get(source)
    if not isinstance(items, list):
        errors.append(f"{where}: choices_from {source} names no list in the content file")
        return []
    return [{"name": item.get("title", item["key"]), "value": item["key"]} for item in items]


def _option(option: dict, content: dict, where: str, errors: list[str]) -> dict:
    kind = option.get("type", "string")
    if kind not in OPTION_TYPES:
        errors.append(f"{where}: unknown option type {kind}")
    result: dict = {
        "name": option["name"],
        "description": option.get("description", ""),
        "type": OPTION_TYPES.get(kind, 3),
    }
    if option.get("required"):
        result["required"] = True
    choices = _choices(option, content, f"{where} option {option['name']}", errors)
    if choices:
        result["choices"] = choices
    for key in ("min_value", "max_value", "max_length"):
        if key in option:
            result[key] = option[key]
    return result


def _sorted_options(options: list[dict]) -> list[dict]:
    # Discord wants the required options first
    return [o for o in options if o.get("required")] + [o for o in options if not o.get("required")]


def registration(content: dict, status_enabled: bool) -> tuple[list[dict], list[str]]:
    """The commands to register and the problems found while building them."""
    errors: list[str] = []
    commands: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for entry in content.get("commands", []):
        name = entry.get("name", "")
        if name == "status" and not status_enabled:
            continue
        kind = MESSAGE if entry.get("type") == "message" else CHAT_INPUT
        where = f"command {name}"
        if (name, kind) in seen:
            errors.append(f"{where} is listed twice")
        seen.add((name, kind))
        command: dict = {"name": name, "type": kind, "contexts": [0], "integration_types": [0]}
        if kind == CHAT_INPUT:
            description = entry.get("description", "")
            command["description"] = description
            if not name or len(name) > 32 or name != name.lower() or " " in name:
                errors.append(f"{where}: a name is lower case, 1 to 32 characters, with no spaces")
            if not 1 <= len(description) <= 100:
                errors.append(f"{where}: the description is 1 to 100 characters")
        else:
            command["description"] = ""
            if not name or len(name) > 32:
                errors.append(f"{where}: a name is 1 to 32 characters")
        options = [_option(o, content, where, errors) for o in entry.get("options", [])]
        options = _sorted_options(options)
        if entry.get("share"):
            options.append({"name": "share", "description": SHARE_DESCRIPTION, "type": OPTION_TYPES["boolean"]})
        subs = []
        for sub in entry.get("subcommands", []):
            sub_options = _sorted_options(
                [_option(o, content, f"{where} {sub['name']}", errors) for o in sub.get("options", [])]
            )
            item = {"name": sub["name"], "description": sub.get("description", ""), "type": 1}
            if sub_options:
                item["options"] = sub_options
            subs.append(item)
        if subs:
            options = subs
        if len(options) > 25:
            errors.append(f"{where}: at most 25 options")
        for option in options:
            if len(option.get("choices", [])) > 25:
                errors.append(f"{where}: at most 25 choices for {option['name']}")
            for choice in option.get("choices", []):
                if not 1 <= len(str(choice["name"])) <= 100 or len(str(choice["value"])) > 100:
                    errors.append(f"{where}: a choice of {option['name']} is too long")
            if not 1 <= len(option["description"]) <= 100:
                errors.append(f"{where}: option {option['name']} needs a description of 1 to 100 characters")
        if options:
            command["options"] = options
        if entry.get("staff"):
            command["default_member_permissions"] = STAFF_PERMISSION
        commands.append(command)
    if len(commands) > MAX_COMMANDS:
        errors.append("a server may hold at most 100 commands for one application")
    return commands, errors


def canonical(command: dict) -> dict:
    """The parts of a command that carry meaning, so one built here compares with one read back."""
    result: dict = {"name": command["name"], "type": command.get("type", 1)}
    if command.get("description"):
        result["description"] = command["description"]
    if command.get("default_member_permissions"):
        result["default_member_permissions"] = str(command["default_member_permissions"])
    if command.get("options"):
        result["options"] = [_canonical_option(o) for o in command["options"]]
    return result


def _canonical_option(option: dict) -> dict:
    result = {"name": option["name"], "type": option["type"], "description": option.get("description", "")}
    if option.get("required"):
        result["required"] = True
    if option.get("choices"):
        result["choices"] = [{"name": c["name"], "value": c["value"]} for c in option["choices"]]
    for key in ("min_value", "max_value", "max_length"):
        if option.get(key) is not None:
            result[key] = option[key]
    if option.get("options"):
        result["options"] = [_canonical_option(o) for o in option["options"]]
    return result


def writable(command: dict) -> dict:
    """An existing command as it must be sent back in a bulk overwrite."""
    keep = ("name", "type", "description", "options", "default_member_permissions", "contexts", "integration_types")
    return {k: command[k] for k in keep if k in command and command[k] is not None}


def export_json(content: dict) -> str:
    """The content as JSON for the worker.

    The form is the one the worker's own build step writes, so either tool can check the file.
    """
    return json.dumps(content, indent=2, ensure_ascii=False) + "\n"
