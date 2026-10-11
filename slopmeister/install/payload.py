"""Build the rendered configuration payload for a selected plot."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import re
import shlex
import stat

from slopmeister.install import snapshot as session_snapshot
from slopmeister.install.models import InstallContext, PayloadContext, ToolPayload
from slopmeister.install.preflight import refuse, safe_path
from slopmeister.plots import load_all
from slopmeister.render.settings import native_tools

GIT_HISTORY_COMMANDS = ("commit", "merge", "rebase", "cherry-pick", "revert", "am", "pull")
# Sessions commit their recorded vault paths when they hand back finished work. Only this
# subcommand, which takes named paths, runs without a question, see docs/vault-version-control.md.
VAULT_COMMIT = "slopmeister-vault commit"
DENY_COMMIT = (
    "Agent commit permission for this plot is deny: the agent has no standing authority to create "
    "commits or push, and only the operator can tell it to. When the operator explicitly asks for "
    "a commit or push in this conversation, run that command through the native tool action. The "
    "configured reviewer checks that the operator explicitly approved that exact command once; "
    "without that instruction leave the change uncommitted and report it. Approval does not "
    "change the saved permission."
)
DIRECTORY_SHIPPING = (
    "Agent shipping permission for this session is deny. No push or PR write, including during "
    "finalize."
)


def declaration(target: str) -> tuple[Path, dict]:
    root = Path(__file__).resolve().parents[2]
    declarations = Path(os.environ.get("PLOT_DECLARATIONS", root / "plots"))
    data = load_all(declarations).get(target, {})
    if "target" not in data:
        refuse("a declared launchable plot is required")
    return root, data


def permission_paragraph(context: PayloadContext) -> bytes:
    if context.directory:
        commit = "This session runs outside any repository. There is nothing to commit."
    elif context.permission == "allow":
        commit = (
            "Agent commit permission for this plot is allow. Agent commits are allowed in this "
            "session's repository. This grants no push, merge or other remote write."
        )
    else:
        commit = DENY_COMMIT
    if context.directory:
        shipping = DIRECTORY_SHIPPING
    elif context.shipping == "allow" and context.permission == "allow":
        shipping = (
            "Agent shipping permission for this session is allow. Ordinary push and PR "
            "create/update are allowed only for the saved repository and current non-default "
            "task branch through ship, GitHub enforces branch protection. Merge and finalize "
            "remain operator-controlled."
        )
    else:
        shipping = (
            "Agent shipping permission for this session is deny: there is no standing authority "
            "to push or create or update a PR. An explicit operator instruction may approve the "
            "fixed ship command once; approval changes no saved permission and grants no merge or "
            "stronger remote action."
        )
    return (commit + "\n" + shipping).encode()


def _manifest(context: PayloadContext) -> tuple[list[dict[str, str]], set[str]]:
    manifest = context.root / "dist/manifest.tsv"
    safe_path(manifest)
    with manifest.open() as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    varied = {
        row["name"].removeprefix(context.target + "/")
        for row in rows
        if row["kind"] == "target-skill" and row["plot"] == context.target
    }
    return rows, varied


def _skill_names(rows: list[dict[str, str]], varied: set[str]) -> list[str]:
    names = {row["name"] for row in rows if row["kind"] == "skill"}
    if not names:
        refuse("rendered shared skills are incomplete")
    return sorted(names | varied)


def _skill_source(tool: ToolPayload, name: str, varied: set[str]) -> Path:
    source = tool.context.root / "dist" / tool.tool
    if name in varied:
        return source / "targets" / tool.context.target / "skills" / name
    return source / "skills" / name


def _add_skill(files: dict, source: Path, destination: str) -> None:
    safe_path(source)
    if not (source / "SKILL.md").is_file():
        refuse("rendered skill entrypoint is missing: " + str(source))
    for path in source.rglob("*"):
        safe_path(path)
        if path.is_dir():
            continue
        if not path.is_file():
            refuse("unsafe skill payload: " + str(path))
        relative = destination + "/" + path.relative_to(source).as_posix()
        files[relative] = (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))


def _tool_payload(tool: ToolPayload) -> None:
    context = tool.context
    source = context.root / "dist" / tool.tool / "plots" / (context.target + ".md")
    safe_path(source)
    tool.files[tool.agreement] = (
        source.read_bytes().rstrip(b"\n") + b"\n\n" + permission_paragraph(context) + b"\n",
        0o644,
    )
    rows, varied = _manifest(context)
    for name in _skill_names(rows, varied):
        if not re.fullmatch("[a-z0-9-]+", name):
            refuse("unsafe skill name in rendered manifest")
        skill = _skill_source(tool, name, varied)
        _add_skill(tool.files, skill, tool.native + "/skills/" + name)


def payload(context: PayloadContext) -> tuple[dict[str, tuple[bytes, int]], dict]:
    files: dict[str, tuple[bytes, int]] = {}
    _tool_payload(ToolPayload(files, context, "claude", ".claude", "CLAUDE.md"))
    _tool_payload(ToolPayload(files, context, "codex", ".agents", "AGENTS.md"))
    source = context.root / "dist/codex/rules/permissions.rules"
    safe_path(source)
    files[".codex/rules/permissions.rules"] = (source.read_bytes(), 0o644)
    settings_path = context.root / "dist/claude/settings.json"
    safe_path(settings_path)
    settings = json.loads(settings_path.read_text())
    if not isinstance(settings, dict):
        refuse("rendered Claude settings must be an object")
    return files, settings


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
    writable = _temporary_roots()
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
    unsafe = candidate == Path.home().resolve() or candidate.stat().st_uid != os.getuid()
    if not temporary or unsafe:
        refuse("TMPDIR must be a current-user macOS temporary directory")
    if str(candidate) not in roots:
        roots.append(str(candidate))
    return roots


def _codex_rules(context: InstallContext) -> None:
    review = [str(context.root / "bin/slopmeister"), "review", "review"]
    for name, command, why in (
        ("review.rules", review, "Slopmeister read-only cross-tool review"),
        ("vault-commit.rules", VAULT_COMMIT.split(), "Slopmeister named-path vault commit"),
    ):
        rule = (
            f'prefix_rule(pattern={json.dumps(command)}, decision="allow", justification="{why}")\n'
        )
        context.files[f".codex/rules/{name}"] = (rule.encode(), 0o644)


def _add_settings(context: InstallContext, values: tuple[dict, dict, list[str], str]) -> None:
    permissions, hooks, writable, review = values
    if not context.directory and context.permission == context.shipping == "allow":
        path = Path("skills/update-prs") / "scripts" / "update.py"
        pattern = json.dumps(["python3", str(context.repo / ".agents" / path)])
        rule = f'prefix_rule(pattern={pattern}, decision="allow", justification="Bot PR writes")\n'
        context.files[".codex/rules/update-pr.rules"] = (rule.encode(), 0o644)
        claude = context.repo / ".claude" / path
        permissions.setdefault("allow", []).append(f"Bash(python3 {claude} *)")
    # Launched Claude sessions run without the Bash sandbox, see docs/plot-shape.md. Stated
    # explicitly because --settings wins over a home setting that would otherwise re-enable it.
    access = {"permissions": permissions, "hooks": hooks, "sandbox": {"enabled": False}}
    if "autoMode" in context.settings:
        access["autoMode"] = context.settings.pop("autoMode")
    context.files[".claude/access-settings.json"] = ((json.dumps(access) + "\n").encode(), 0o644)
    settings = json.dumps(context.settings, indent=2) + "\n"
    context.files[".claude/settings.json"] = (settings.encode(), 0o644)
    _codex_rules(context)
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
