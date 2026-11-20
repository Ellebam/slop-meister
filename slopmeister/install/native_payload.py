"""Build the fixed native-client permissions and writable roots for a new session."""

import json
import os
from pathlib import Path
import re
import shlex
import stat

from slopmeister.install import snapshot as session_snapshot
from slopmeister.install.check import CheckContext, check, state_directory
from slopmeister.install.models import InstallContext
from slopmeister.install.preflight import refuse, safe_path
from slopmeister.removal import SCRATCH
from slopmeister.render.settings import native_tools, permission_contract

GIT_HISTORY_COMMANDS = ("commit", "merge", "rebase", "cherry-pick", "revert", "am", "pull")
VAULT_COMMIT = shlex.join([str(Path.home() / ".vault-git/bin/slopmeister-vault"), "commit"])


def add_native_payload(context: InstallContext) -> None:
    settings = context.settings
    settings["claudeMdExcludes"] = settings.get("claudeMdExcludes", []) + [
        str(context.repo / "**"),
        *(str(Path(path) / "**") for path in context.grants),
    ]
    _add_git_approval(context)
    permissions = settings.pop("permissions", {})
    binary = shlex.quote(str(context.root / "bin/slopmeister"))
    review = f"{binary} review review *"
    permissions.setdefault("allow", []).append(f"Bash({review})")
    permissions["allow"].append(f"Bash({VAULT_COMMIT} *)")
    permissions.setdefault("ask", []).append(f"Bash({binary} review replace *)")
    permissions.setdefault("deny", []).append("Edit(~/.local/state/slopmeister/**)")
    scratch = context.repo / SCRATCH
    safe_path(scratch)
    if scratch.exists():
        refuse("session scratch directory already exists")
    writable = [str(scratch), *_temporary_roots()]
    editable = list(dict.fromkeys((str(context.repo), *context.grants, *writable)))
    permissions["allow"].extend("Edit(/" + path + "/**)" for path in editable)
    permissions.setdefault("additionalDirectories", []).extend([*context.grants, *writable])
    hooks = settings.pop("hooks", {})
    root = context.state_dir / session_snapshot.DIRECTORY
    session_snapshot.bake(context.files, root, companion=bool(context.request.session))
    _add_settings(context, (permissions, hooks, writable, review))


def _temporary_roots() -> list[str]:
    system = Path("/tmp").resolve()
    roots = [str(system)]
    raw = os.environ.get("TMPDIR")
    if not raw:
        return roots
    candidate = Path(raw)
    if not candidate.is_absolute() or not candidate.is_dir():
        refuse("TMPDIR must be an absolute existing directory")
    candidate = candidate.resolve()
    mac = re.fullmatch(r"/private/var/folders/[^/]+/[^/]+/T(?:/.*)?", str(candidate))
    temporary = candidate == system or candidate.is_relative_to(system) or bool(mac)
    temporary = temporary or _session_temporary(candidate)
    unsafe = candidate == Path.home().resolve() or candidate.stat().st_uid != os.getuid()
    if not temporary or unsafe:
        refuse("TMPDIR must be a current-user macOS temporary directory")
    if str(candidate) not in roots:
        roots.append(str(candidate))
    return roots


def _session_temporary(candidate: Path) -> bool:
    selected = os.environ.get("SLOPMEISTER_SESSION_WORKSPACE")
    if not selected:
        return False
    root = Path(selected).resolve()
    if candidate != root / SCRATCH:
        return False
    directory, _ = state_directory(root)
    safe_path(directory / "state.json")
    state = json.loads((directory / "state.json").read_text())
    if state.get("scratch") != SCRATCH or stat.S_IMODE(candidate.stat().st_mode) != 0o700:
        return False
    check(CheckContext(root, state["plot"], state["commit"], state["grants"]))
    return True


def _codex_rules(context: InstallContext, permissions: dict) -> None:
    binary = str(context.root / "bin/slopmeister")
    review = [binary, "review", "review"]
    add = [binary, "repository", "add"]
    vault = shlex.split(VAULT_COMMIT)
    policies = permission_contract(context.root / "src/permissions.toml")["self_release"]
    releases = [[binary, *policy["prefix"].split(), str(context.repo)] for policy in policies]
    permissions.setdefault("allow", []).extend(f"Bash({shlex.join(item)})" for item in releases)
    permissions.setdefault("ask", []).append(f"Bash({shlex.join(add)} *)")
    for name, command, decision, why in (
        ("review.rules", review, "allow", "Slopmeister read-only cross-tool review"),
        ("vault-commit.rules", vault, "allow", "Slopmeister named-path vault commit"),
        *(
            ("self-release.rules", release, "allow", policy["why"])
            for release, policy in zip(releases, policies, strict=True)
        ),
        (
            "repository-add.rules",
            add,
            "prompt",
            "Add only the exact repository the operator approved for this session.",
        ),
    ):
        rule = f"prefix_rule(pattern={json.dumps(command)}, "
        rule += f'decision="{decision}", justification={json.dumps(why)})\n'
        path = f".codex/rules/{name}"
        previous = context.files.get(path, (b"", 0o644))[0]
        context.files[path] = (previous + rule.encode(), 0o644)


def _ci_rerun_rules(context: InstallContext, permissions: dict) -> None:
    policy = permission_contract(context.root / "src/permissions.toml")["ci_rerun"]
    rules = []
    for native in (".agents", ".claude"):
        directory = context.repo / native / "skills/ci-rerun"
        for fixed in (directory, context.repo / native / "skills/ship"):
            permissions.setdefault("deny", []).append("Edit(/" + str(fixed) + "/**)")
        if not context.directory and not context.request.proof_owner:
            command = ["python3", str(directory / "scripts" / "ci_rerun.py")]
            permissions.setdefault("allow", []).append("Bash(" + shlex.join(command) + " *)")
            rules.append(
                f'prefix_rule(pattern={json.dumps(command)}, decision="allow", '
                f"justification={json.dumps(policy['why'])})"
            )
    context.files[".codex/rules/ci-rerun.rules"] = (("\n".join(rules) + "\n").encode(), 0o644)


def _add_settings(context: InstallContext, values: tuple[dict, dict, list[str], str]) -> None:
    permissions, hooks, writable, review = values
    # Launched Claude sessions run without the Bash sandbox, see docs/plot-shape.md. Stated
    # explicitly because --settings wins over a home setting that would otherwise re-enable it.
    _codex_rules(context, permissions)
    _ci_rerun_rules(context, permissions)
    access = {"permissions": permissions, "hooks": hooks, "sandbox": {"enabled": False}}
    if "autoMode" in context.settings:
        access["autoMode"] = context.settings.pop("autoMode")
    context.files[".claude/access-settings.json"] = ((json.dumps(access) + "\n").encode(), 0o644)
    settings = json.dumps(context.settings, indent=2) + "\n"
    context.files[".claude/settings.json"] = (settings.encode(), 0o644)
    context.files[".codex/config.toml"] = (native_tools(context, writable), 0o644)


SHIP_ENTRY = Path("skills", "ship", "scripts", "ship.py")
PUSH_ONLY = (
    "The fixed ship helper pushes HEAD without force only to this session's recorded branch "
    "and new pre-release tags at HEAD, and refuses the default branch and every other checkout"
)


def _add_git_approval(context: InstallContext) -> None:
    if context.directory:
        return
    commands = list(GIT_HISTORY_COMMANDS) if context.permission == "deny" else []
    commands.append("push")
    patterns = []
    for command in commands:
        patterns.extend((["git", command], ["git", "-C", str(context.repo), command]))
    ship = [["python3", str(context.repo / tree / SHIP_ENTRY)] for tree in (".agents", ".claude")]
    allowed = context.permission == "allow" and context.shipping == "allow"
    if not allowed:
        patterns.extend(ship)
    order = permission_contract(context.root / "src/permissions.toml")["order"]
    why = json.dumps("Explicit operator intent required. " + order)
    tail = f', decision="prompt", justification={why})'
    rules = ["prefix_rule(pattern=" + json.dumps(pattern) + tail for pattern in patterns]
    if allowed:
        pushes = [[*command, "--push-only"] for command in ship]
        tail = f', decision="allow", justification={json.dumps(PUSH_ONLY)})'
        rules += ["prefix_rule(pattern=" + json.dumps(pattern) + tail for pattern in pushes]
        allow = ["Bash(" + shlex.join(pattern) + " *)" for pattern in pushes]
        context.settings.setdefault("permissions", {}).setdefault("allow", []).extend(allow)
    context.files[".codex/rules/git-permission.rules"] = (("\n".join(rules) + "\n").encode(), 0o644)
    asks = ["Bash(" + " ".join(pattern) + " *)" for pattern in patterns]
    context.settings.setdefault("permissions", {}).setdefault("ask", []).extend(asks)
