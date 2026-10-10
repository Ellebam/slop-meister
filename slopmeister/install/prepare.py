"""Orchestrate preparation of fixed session configuration."""

from __future__ import annotations

import os
from pathlib import Path
import re

from slopmeister.install.check import CheckContext, check
from slopmeister.install.models import InstallContext, InstallRequest
from slopmeister.install.payload import PayloadContext, add_native_payload, declaration, payload
from slopmeister.install.preflight import ROOTS, refuse, safe_path
from slopmeister.install.service_actions import ActionContext, action_payload, admit
from slopmeister.install.workspace import prepare_directory, prepare_repository, write_workspace
from slopmeister.plots import load_all
from slopmeister.render.settings import permission_contract

READ_EXCEPTION = (
    "Selected fixed service read action: after native review of its exact delivered entry, "
    "permit internal service-account document retrieval and masked field "
    "resolution for the selected provider read. This exception grants no direct secret reads, "
    "arbitrary consumer, desktop fallback, credential output or provider writes."
)


def _context(req: InstallRequest) -> InstallContext:
    if req.dispatcher_jira and (req.action, req.target) != ("--directory", "slopmeister"):
        refuse("dispatcher Jira delivery requires a fresh Slopmeister directory")
    root, data = declaration(req.target)
    repo = Path(os.path.abspath(req.workspace))
    safe_path(repo)
    checking = req.action == "--check"
    directory = req.action == "--directory" or checking and not (repo / ".git").exists()
    target = data["target"]
    permission = "-" if directory else target.get("repository", {}).get("commit", "-")
    shipping = "deny" if directory else target.get("repository", {}).get("shipping", "deny")
    grants = sorted(set(str(Path(path).resolve()) for path in req.grants))
    if any(not Path(path).is_dir() for path in grants):
        refuse("additional directory is missing")
    state = dict(
        version=3,
        worktree=str(repo),
        plot=req.target,
        commit=permission,
        directory=directory,
        grants=grants,
        allocation=req.allocation,
        shipping=shipping,
        service_actions=target.get("service_actions", []),
        bloom=target.get("bloom", "local"),
    )
    return InstallContext(
        req, root, data, repo, directory, permission, shipping, grants, state=state
    )


def _existing(context: InstallContext) -> bool:
    if context.request.action != "--check":
        return False
    request = CheckContext(context.repo, context.request.target, context.permission, context.grants)
    state = check(request)
    if state.get("service_actions", []) != context.data["target"].get("service_actions", []):
        refuse(
            "selected service actions changed; preserve this workspace and start a fresh session"
        )
    return True


def _validate_allocation(context: InstallContext) -> None:
    allocation = context.request.allocation
    if allocation is not None and (
        not re.fullmatch(r"[A-Za-z0-9._-]+", allocation)
        or allocation in ROOTS
        or allocation in (".", "..")
    ):
        refuse("allocation must be a safe basename outside the configuration roots")


def _dispatcher_actions(context: InstallContext) -> tuple[dict, dict, str]:
    directory = Path(os.environ.get("PLOT_DECLARATIONS", context.root / "plots"))
    selected = [
        ActionContext(
            context.root, name, {"service_actions": ["jira-read"]}, context.repo, namespaced=True
        )
        for name, data in load_all(directory).items()
        if "jira-read" in data.get("target", {}).get("service_actions", [])
    ]
    if not selected:
        return {}, {}, ""
    try:
        admit()
    except ValueError:
        return (
            {},
            {},
            "\n".join(f"{item.plot}: Jira reader unavailable; report unknown" for item in selected),
        )
    return action_payload(selected[0], selected)


def _action_payload(context: InstallContext) -> tuple[dict, dict, str]:
    if context.request.dispatcher_jira:
        return _dispatcher_actions(context)
    actions = context.state["service_actions"]
    if not actions:
        return {}, {}, ""
    admit()
    return action_payload(
        ActionContext(context.root, context.request.target, context.data["target"], context.repo)
    )


def _service_actions(context: InstallContext) -> None:
    files, permissions, instructions = _action_payload(context)
    if not instructions:
        return
    context.files.update(files)
    for key, rules in permissions.items():
        context.settings.setdefault("permissions", {}).setdefault(key, []).extend(rules)
    for agreement in ("AGENTS.md", "CLAUDE.md"):
        content, mode = context.files[agreement]
        context.files[agreement] = (content + b"\n" + instructions.encode(), mode)
    if not permissions.get("ask"):
        return
    allow = context.settings.setdefault("autoMode", {}).setdefault("allow", ["$defaults"])
    if context.request.dispatcher_jira or any(
        action.endswith("-read") for action in context.state["service_actions"]
    ):
        allow.append(READ_EXCEPTION)
    if any(action.endswith("-write") for action in context.state["service_actions"]):
        policies = permission_contract(context.root / "src/permissions.toml")["service_action"]
        allow.extend(
            entry["credential_allow"]
            for entry in policies
            if entry["action"] in context.state["service_actions"]
        )


def prepare(request: InstallRequest) -> None:
    context = _context(request)
    if _existing(context):
        return
    _validate_allocation(context)
    payload_context = PayloadContext(
        context.root, request.target, context.permission, context.directory, context.shipping
    )
    context.files, context.settings = payload(payload_context)
    _service_actions(context)
    if context.directory:
        prepare_directory(context)
    elif not prepare_repository(context):
        return
    add_native_payload(context)
    write_workspace(context)
    check(CheckContext(context.repo, request.target, context.permission, context.grants))
    print("Slopmeister configuration prepared")
