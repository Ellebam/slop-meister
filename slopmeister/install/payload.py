"""Build the rendered configuration payload for a selected plot."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import re
import stat

from slopmeister.install.models import PayloadContext, ToolPayload
from slopmeister.install.native_payload import add_native_payload as add_native_payload
from slopmeister.install.preflight import refuse, safe_path
from slopmeister.plots import load_all

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
