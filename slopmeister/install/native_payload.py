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
VAULT_COMMIT = "slopmeister-vault commit"


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
    session_snapshot.bake(context.files, root)
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
    review = [str(context.root / "bin/slopmeister"), "review", "review"]
    policy = permission_contract(context.root / "src/permissions.toml")["self_release"]
    release = [review[0], *policy["prefix"].split(), str(context.repo)]
    permissions.setdefault("allow", []).append(f"Bash({shlex.join(release)})")
    for name, command, why in (
        ("review.rules", review, "Slopmeister read-only cross-tool review"),
        ("vault-commit.rules", VAULT_COMMIT.split(), "Slopmeister named-path vault commit"),
        ("self-release.rules", release, policy["why"]),
    ):
        rule = (
            f'prefix_rule(pattern={json.dumps(command)}, decision="allow", justification="{why}")\n'
        )
        context.files[f".codex/rules/{name}"] = (rule.encode(), 0o644)


def _add_settings(context: InstallContext, values: tuple[dict, dict, list[str], str]) -> None:
    permissions, hooks, writable, review = values
    # Launched Claude sessions run without the Bash sandbox, see docs/plot-shape.md. Stated
    # explicitly because --settings wins over a home setting that would otherwise re-enable it.
    _codex_rules(context, permissions)
    access = {"permissions": permissions, "hooks": hooks, "sandbox": {"enabled": False}}
    if "autoMode" in context.settings:
        access["autoMode"] = context.settings.pop("autoMode")
    context.files[".claude/access-settings.json"] = ((json.dumps(access) + "\n").encode(), 0o644)
    settings = json.dumps(context.settings, indent=2) + "\n"
    context.files[".claude/settings.json"] = (settings.encode(), 0o644)
    context.files[".codex/config.toml"] = (native_tools(context, writable), 0o644)


def _add_git_approval(context: InstallContext) -> None:
    if context.directory:
        return
    commands = list(GIT_HISTORY_COMMANDS) if context.permission == "deny" else []
    commands.append("push")
    patterns = []
    for command in commands:
        patterns.extend((["git", command], ["git", "-C", str(context.repo), command]))
    if context.permission != "allow" or context.shipping != "allow":
        ship = Path("skills", "ship", "scripts", "ship.py")
        patterns.extend(
            ["python3", str(context.repo / tree / ship)] for tree in (".agents", ".claude")
        )
    rules = [
        "prefix_rule(pattern="
        + json.dumps(pattern)
        + ', decision="prompt", justification="Explicit operator intent required")'
        for pattern in patterns
    ]
    asks = ["Bash(" + " ".join(pattern) + " *)" for pattern in patterns]
    context.files[".codex/rules/git-permission.rules"] = (
        ("\n".join(rules) + "\n").encode(),
        0o644,
    )
    context.settings.setdefault("permissions", {}).setdefault("ask", []).extend(asks)
