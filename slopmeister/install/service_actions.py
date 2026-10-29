"""Validate profiles and construct fixed native service-action payloads."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
from urllib.parse import urlsplit

from slopmeister.render.settings import service_binding, service_registration, service_rules
from slopmeister.session.service_actions import runtime
from slopmeister.session.service_actions.constants import ORIGIN, PYTHON, PYTHON_FLAGS, SUCCESS
from slopmeister.session.service_actions.jira_find import backlog_query

ARGUMENTS = {"confluence-read": " --page <PAGE_ID_OR_URL>", "jira-read": " --issue <KEY>"}
_MODULES = (
    "__init__ arguments confluence confluence_children confluence_common confluence_page "
    "confluence_write constants jira jira_find jira_issue jira_related jira_write operations "
    "native_gate native_process process provider runtime supervisor transport wire writes"
)
CONSUMER_FILES = (
    "entry.py",
    "native_tool.py",
    "service_actions/openssl.cnf",
    *(f"service_actions/{name}.py" for name in _MODULES.split()),
)
PROFILE_KEYS = set(
    ["action", "plot", "origin", "expected_user", "account_id", "vault_id", "vault_name"]
    + ["pat_ref", "password_ref", "certificate_document", "token_file"]
)
CERTIFICATE_KEYS = {"password_ref", "certificate_document"}
PROFILE_ROOT = ".config/slopmeister/access"
DIRECT_MODULES = tuple(
    [executable, *PYTHON_FLAGS, "-m", "service_actions.supervisor"]
    for executable in (str(PYTHON), "python3")
)


@dataclass(frozen=True)
class ActionContext:
    root: Path
    plot: str
    target: dict
    workspace: Path
    profile_root: Path | None = None
    native: bool = True
    namespaced: bool = False


def _valid_profile_shape(data: object) -> bool:
    if not isinstance(data, dict) or set(data) - {"server_ca", "backlog_jql"} not in (
        PROFILE_KEYS,
        PROFILE_KEYS - CERTIFICATE_KEYS,
    ):
        return False
    if "backlog_jql" in data and data["action"] != "jira-read":
        return False
    return all(
        isinstance(value, str)
        and value
        and len(value) <= 2048
        and not any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)
        for value in data.values()
    )


def _validate_origin(data: dict) -> None:
    if not re.fullmatch(ORIGIN, data["origin"]):
        raise ValueError(
            "action profile requires one HTTPS base URL with an optional application path"
        )
    try:
        port = urlsplit(data["origin"]).port
    except ValueError:
        raise ValueError("action profile has an invalid port") from None
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("action profile has an invalid port")


def _validate_references(data: dict) -> None:
    for key in ("pat_ref", "password_ref"):
        if key not in data:
            continue
        parts = data[key].removeprefix("op://").split("/")
        if (
            not data[key].startswith("op://")
            or len(parts) != 3
            or not all(parts)
            or parts[0] not in (data["vault_id"], data["vault_name"])
        ):
            raise ValueError("action profile references must stay in the selected vault")
        if key == "password_ref" and parts[1] != data["certificate_document"]:
            raise ValueError("action profile password must belong to its certificate document")


def validate_profile(data: object, plot: str, action: str) -> dict:
    if not _valid_profile_shape(data):
        raise ValueError("action profile has missing, unknown or invalid fields")
    if data["plot"] != plot or data["action"] != action:
        raise ValueError("action profile does not match the selected plot/action")
    if "backlog_jql" in data:
        backlog_query(data["backlog_jql"])
    _validate_origin(data)
    for key in ("account_id", "vault_id"):
        if not re.fullmatch(r"[A-Za-z0-9]{26}", data[key]):
            raise ValueError("action profile requires account and vault IDs")
    if not all(Path(data[key]).is_absolute() for key in ("token_file", "server_ca") if key in data):
        raise ValueError("action profile requires an absolute credential-file path")
    for key in ("certificate_document", "vault_name"):
        if key in data and (data[key].startswith("-") or "/" in data[key]):
            raise ValueError("action profile has an invalid document or vault name")
    _validate_references(data)
    return data


def read_profile(path: Path, plot: str, action: str) -> dict:
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("action profile path may not contain symlinks")
    try:
        with path.open("rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_size > 16384
            ):
                raise ValueError("action profile requires an owned regular 0600 file")
            data = json.loads(stream.read(16385))
    except OSError, UnicodeError, json.JSONDecodeError:
        raise ValueError(
            "action profile is missing or unreadable; provision it before launch"
        ) from None
    return validate_profile(data, plot, action)


def _consumer(context: ActionContext, action: str) -> tuple[dict[str, bytes], str]:
    if action not in SUCCESS:
        raise ValueError("declared service action has no checked-in fixed consumer")
    source = context.root / "slopmeister/session/service_actions"
    if not source.is_dir():
        raise ValueError("declared service action has no checked-in fixed consumer")
    content = {}
    for name in CONSUMER_FILES:
        path = source / name.removeprefix("service_actions/")
        if any(parent.is_symlink() for parent in (path, *path.parents)) or not path.is_file():
            raise ValueError("unsafe fixed consumer source")
        content[name] = path.read_bytes()
    encoded = b"".join(name.encode() + b"\0" + content[name] for name in CONSUMER_FILES)
    return content, hashlib.sha256(encoded).hexdigest()


def admit() -> None:
    if absent := runtime.missing():
        raise ValueError(
            "selected service action prerequisites are missing before session creation: "
            + ", ".join(absent)
            + "; provider was not contacted"
        )


def _add_action(
    context: ActionContext, action: str, entries: dict
) -> tuple[list[str], list[str], list[str]]:
    content, revision = _consumer(context, action)
    source_action = action.replace("-write", "-read")
    root = Path.home() / PROFILE_ROOT if context.profile_root is None else context.profile_root
    path = root / context.plot / (source_action + ".json")
    data = read_profile(path, context.plot, source_action)
    rules, asks, commands = [], [], []
    for native in (".codex", ".claude"):
        name = f"{context.plot}/{action}" if context.namespaced else action
        relative = native + "/service-actions/" + name
        entries.update({relative + "/" + name: (value, 0o444) for name, value in content.items()})
        if action.endswith("-write"):
            data["action"] = action
            data.pop("backlog_jql", None)
            data["native"] = service_binding(context, native, action)
        entries[relative + "/config.json"] = ((json.dumps(data, indent=2) + "\n").encode(), 0o400)
        entries[relative + "/revision"] = ((revision + "\n").encode(), 0o444)
        entry = context.workspace / relative / "entry.py"
        patterns = [[str(PYTHON), *PYTHON_FLAGS, str(entry)]]
        more_rules, more_asks = service_rules(patterns, context.root, action)
        rules.extend(more_rules)
        asks.extend(more_asks)
        arguments = " --backlog" if context.namespaced else ARGUMENTS.get(action, "")
        command = f"`{PYTHON} {' '.join(PYTHON_FLAGS)} {shlex.quote(str(entry))} "
        command += f"--output <PRIVATE_RESULT_FILE>{arguments}`"
        label = f"mcp__{action.replace('-', '_')}__run: " if action.endswith("-write") else ""
        commands.append(f"{label}{command} ({native}, revision {revision[:12]})")
    return rules, asks, commands


def _collect(contexts: list[ActionContext], entries: dict) -> tuple[list, list, list]:
    asks, rules, commands = [], [], []
    pairs = [
        (item, action) for item in contexts for action in item.target.get("service_actions", [])
    ]
    for context, action in pairs:
        if context.namespaced and (
            action != "jira-read" or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", context.plot)
        ):
            raise ValueError("dispatcher requires declared Jira readers")
        try:
            more_rules, more_asks, more_commands = _add_action(context, action, entries)
        except ValueError:
            if not context.namespaced:
                raise
            commands.append(f"{context.plot}: Jira reader unavailable; report unknown")
            continue
        rules.extend(more_rules)
        asks.extend(more_asks)
        commands.extend(more_commands)
    return asks, rules, commands


def action_payload(
    context: ActionContext, selected: list[ActionContext] | None = None
) -> tuple[dict, dict, str]:
    entries = {}
    asks, rules, commands = _collect(selected if selected is not None else [context], entries)
    if not commands:
        return {}, {}, ""
    entries.update(service_registration(context))
    rules.extend(
        "prefix_rule(pattern=" + json.dumps(module) + ', decision="forbidden")'
        for module in DIRECT_MODULES
    )
    direct_denies = ["Bash(" + " ".join(module) + " *)" for module in DIRECT_MODULES]
    entries[".codex/rules/service-actions.rules"] = (
        ("\n".join(dict.fromkeys(rules)) + "\n").encode(),
        0o644,
    )
    denies = [
        "Edit(/" + str(context.workspace / native / "service-actions") + "/**)"
        for native in (".claude", ".codex")
    ]
    permissions = {"ask": list(dict.fromkeys(asks)), "deny": [*denies, *direct_denies]}
    instructions = (context.root / "src/service-actions/instructions.md").read_text().rstrip()
    instructions += (
        "\n\nSelected commands\n\n" + "\n".join("- " + command for command in commands) + "\n"
    )
    return entries, permissions, instructions
