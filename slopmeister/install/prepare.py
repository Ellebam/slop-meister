"""Orchestrate preparation of fixed session configuration."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shlex

from slopmeister.install import check
from slopmeister.install import snapshot as session_snapshot
from slopmeister.install.models import InstallContext, InstallRequest
from slopmeister.install.payload import PayloadContext, add_native_payload, declaration, payload
from slopmeister.install.preflight import ROOTS, refuse, safe_path
from slopmeister.install.roles import (
    EVERY_SESSION,
    MANAGER,
    MANAGER_EXCEPTION,
    PROOF,
    PROOF_OWNER_EXCEPTION,
    PROOF_SOFT_DENY,
    WEEKLY,
)
from slopmeister.install.service_actions import ActionContext, action_payload, admit
from slopmeister.install.workspace import (
    prepare_directory,
    prepare_repository,
    record_push_branch,
    write_workspace,
)
from slopmeister.paths import plot_declarations
from slopmeister.plots import load_all
from slopmeister.render.settings import codex_rules, exception_forms, permission_contract

# Launcher and removal helpers of the invoking checkout. Each checks claims, occupancy and
# uncommitted work itself. The literal -- ends Task's own options, so another Taskfile or a
# second task name matches no rule.
HELPERS = (
    "task --dir {root} plot-session --",
    "task --dir {root} slot:up --",
    "task --dir {root} slot:down --",
    "task --dir {root} workspace:remove --",
    "{root}/bin/slopmeister workspace-remove",
)
# The removal parser accepts every abbreviation of --force, so the rule asks from --f on.
HELPER_ASKS = ["--f", "--abandon"]


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
    if req.proof_owner:
        shipping = "deny"
    grants = sorted(set(str(Path(path).resolve()) for path in req.grants))
    if any(not Path(path).is_dir() for path in grants):
        refuse("additional directory is missing")
    state = dict(
        version=check.VERSION,
        native_server_pins=True,
        worktree=str(repo),
        plot=req.target,
        commit=permission,
        directory=directory,
        grants=grants,
        allocation=req.allocation,
        shipping=shipping,
        service_actions=target.get("service_actions", []),
        bloom=target.get("bloom", "local"),
        proof_owner=req.proof_owner,
        repository_add=not directory,
        source_identity=session_snapshot.source_identity(root),
        source_root=str(root),
    )
    if req.session:
        state["session"] = req.session
    if req.manager_run:
        state["manager_run"] = req.manager_run
    return InstallContext(
        req, root, data, repo, directory, permission, shipping, grants, state=state
    )


def _existing(context: InstallContext) -> bool:
    if context.request.action != "--check":
        return False
    request = check.CheckContext(
        context.repo, context.request.target, context.permission, context.grants
    )
    state = check.check(request)
    if state.get("service_actions", []) != context.data["target"].get("service_actions", []):
        refuse(
            "selected service actions changed; preserve this workspace and start a fresh session"
        )
    push = context.request.push_branch
    if push:
        if context.directory:
            refuse("a directory session has no branch to push")
        record_push_branch(context.repo, check.state_directory(context.repo)[0], state, push)
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
    directory = plot_declarations(context.root / "plots")
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
    policies = permission_contract(context.root / "src/permissions.toml")["service_action"]
    allow.extend(
        entry["credential_allow"]
        for entry in policies
        if entry["action"] in context.state["service_actions"]
    )


def _role_rules(context: InstallContext) -> None:
    """Apply the contract entries whose decision depends on this session's role."""
    request = context.request
    sender = request.manager or request.dispatcher_jira
    contract = permission_contract(context.root / "src/permissions.toml")
    changed = {}
    for entry in contract["command"]:
        if request.proof_owner and (entry.get("remote_write") or entry.get("terminal_input")):
            changed[entry["prefix"]] = {**entry, "decision": "deny"}
        elif sender and entry.get("terminal_input"):
            changed[entry["prefix"]] = {**entry, "decision": "allow"}
    if sender:
        _helper_rules(context)
    if not changed:
        return
    # Codex takes the strictest matching rule, so the session's file replaces the shared one.
    contract["command"] = [changed.get(entry["prefix"], entry) for entry in contract["command"]]
    context.files[".codex/rules/permissions.rules"] = (codex_rules(contract).encode(), 0o644)
    permissions = context.settings.setdefault("permissions", {})
    for prefix, entry in changed.items():
        forms = (f"Bash({prefix})", f"Bash({prefix} *)")
        permissions.setdefault(entry["decision"], []).extend(forms)


def _helper_rules(context: InstallContext) -> None:
    """A dispatcher or manager runs its checkout's session helpers by rule, in Claude only."""
    permissions = context.settings.setdefault("permissions", {})
    for helper in HELPERS:
        entry = {"prefix": helper.format(root=shlex.quote(str(context.root)))}
        permissions.setdefault("allow", []).append(f"Bash({entry['prefix']} *)")
        asked = exception_forms({**entry, "allow_unless": HELPER_ASKS})
        permissions.setdefault("ask", []).extend(f"Bash({form})" for form in asked)


def _terminal_role(context: InstallContext) -> None:
    manager, owner = context.request.manager, context.request.proof_owner
    text = EVERY_SESSION + (
        "\n" + MANAGER.format(root=shlex.quote(str(context.root))) if manager else ""
    )
    text += "\n" + PROOF.format(name=owner["name"]) if owner else ""
    text += "\n" + WEEKLY if context.request.weekly_update else ""
    for agreement, native in (("AGENTS.md", ".agents"), ("CLAUDE.md", ".claude")):
        content, mode = context.files[agreement]
        instructions = text.encode() + b"\n"
        if manager:
            skill = context.files[f"{native}/skills/plot-session/SKILL.md"][0]
            practices = skill.split(b"\n### Working practices\n", 1)[1].split(b"\n## ", 1)[0]
            instructions += b"\n### Working practices\n" + practices
        context.files[agreement] = (content + instructions, mode)
    mode = context.settings.setdefault("autoMode", {})
    allow = mode.setdefault("allow", ["$defaults"])
    if manager:
        allow.append(MANAGER_EXCEPTION)
    if owner:
        mode.setdefault("soft_deny", ["$defaults"]).append(PROOF_SOFT_DENY)
    else:
        allow.append(PROOF_OWNER_EXCEPTION)


def prepare(request: InstallRequest) -> None:
    context = _context(request)
    if _existing(context):
        return
    _validate_allocation(context)
    payload_context = PayloadContext(
        context.root, request.target, context.permission, context.directory, context.shipping
    )
    context.files, context.settings = payload(payload_context)
    _terminal_role(context)
    _role_rules(context)
    _service_actions(context)
    if context.directory:
        prepare_directory(context)
    elif not prepare_repository(context):
        return
    add_native_payload(context)
    write_workspace(context)
    check.check(
        check.CheckContext(context.repo, request.target, context.permission, context.grants)
    )
    print("Slopmeister configuration prepared")
