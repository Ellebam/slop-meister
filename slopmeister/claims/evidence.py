"""Workspace receipts and native delivery evidence for issue claims."""

from contextlib import redirect_stdout
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile

from slopmeister.claims import github
from slopmeister.install.check import CheckContext, check

RECEIPT = "slopmeister-config/issue.json"


def eligible(plot: str, workspace: Path | None = None) -> bool:
    target = github.declaration(plot)
    permissions = target.get("repository", {})
    if workspace and workspace.is_dir():
        path = receipt_path(workspace)
        if path.with_name("state.json").exists():
            permissions = read(path.with_name("state.json"))
        if path.exists() and read(path).get("tasks") != target["tasks"]:
            raise ValueError("saved issue task source disagrees with this plot")
    allowed = all(permissions.get(key) == "allow" for key in ("commit", "shipping"))
    return target["tasks"] == "github" and allowed


def safe_path(path: Path | str) -> Path:
    resolved = Path(path).absolute()
    if any(part.is_symlink() for part in (resolved, *resolved.parents)):
        raise ValueError("symlinked claim evidence path")
    return resolved


def read(path: Path | str) -> dict:
    value = json.loads(safe_path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError("claim evidence must be an object")
    return value


def save(path: Path | str, value: dict, exclusive: bool = False) -> None:
    target = safe_path(path)
    with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, delete=False) as stream:
        temporary = stream.name
        json.dump(value, stream, indent=2)
        stream.write("\n")
    try:
        os.link(temporary, target) if exclusive else os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def receipt_path(workspace: Path | str) -> Path:
    root = Path(workspace).resolve()
    if Path(github.git(root, "rev-parse", "--show-toplevel")).resolve() != root:
        raise ValueError("issue workspace must be a worktree root")
    git_dir = github.git(root, "rev-parse", "--absolute-git-dir")
    return Path(git_dir) / RECEIPT


def workspace_record(
    workspace: Path, plot: str | None = None, unassociated: bool = False
) -> tuple[github.Repository, Path, dict | None]:
    path = receipt_path(workspace)
    state = read(path.with_name("state.json"))
    selected = plot or state["plot"]
    with redirect_stdout(io.StringIO()):
        check(CheckContext(workspace.resolve(), selected, state["commit"], state["grants"]))
    if not eligible(selected, workspace):
        raise ValueError("existing shipping permission does not allow issue management")
    ctx = github.context(workspace, selected)
    if state["ship_target"]["remote"] != ctx.remote:
        raise ValueError("saved issue repository destination changed")
    if unassociated and not path.exists():
        return ctx, path, None
    saved = read(path)
    validate_receipt(saved, workspace, ctx)
    return ctx, path, saved


def validate_receipt(saved: dict, workspace: Path, ctx: github.Repository) -> None:
    phases = github.ACTIVE | {"released", "closed"}
    valid = (
        saved.get("version") == 1
        and saved.get("workspace") == str(workspace.resolve())
        and saved.get("repository") == ctx.name
        and saved.get("plot") == ctx.plot
        and saved.get("tasks") == "github"
        and saved.get("phase") in phases
    )
    if not valid:
        raise ValueError("saved issue association is inconsistent")
    if saved.get("issue") != github.issue_number(saved.get("issue")):
        raise ValueError("saved issue identifier must be an integer")


def receipts(ctx: github.Repository) -> list[dict]:
    values = []
    main, *linked = github.workspaces(ctx)
    located = [(main, ctx.common / RECEIPT)]
    located += [(workspace, _linked_receipt(ctx, workspace)) for workspace in linked]
    for workspace, path in located:
        if not path.exists():
            continue
        value = read(path)
        if value.get("repository") != ctx.name or value.get("workspace") != str(workspace):
            raise ValueError("registered workspace has conflicting issue evidence")
        if value.get("issue") != github.issue_number(value.get("issue")):
            raise ValueError("saved issue identifier must be an integer")
        if value.get("phase") not in github.ACTIVE | {"released", "closed"}:
            raise ValueError("unknown claim receipt phase")
        values.append(value)
    return values


def _linked_receipt(ctx: github.Repository, workspace: Path) -> Path:
    """This repository's metadata holds the receipt, whatever the worktree's directory became."""
    for pointer in ctx.common.glob("worktrees/*/gitdir"):
        if (pointer.parent / pointer.read_text().strip()).parent.resolve() == workspace:
            return pointer.parent / RECEIPT
    raise ValueError("registered worktree has no Git metadata")


def digest(path: Path | str, kickoff: bool = False) -> str:
    data = safe_path(path).read_bytes()
    return hashlib.sha256(data.rstrip(b"\n") if kickoff else data).hexdigest()


# The OpenCode launcher writes its reduced receipt as Claude-shaped rows.
CLAUDE_SHAPED = ("claude", "opencode")


@dataclass
class Scan:
    native: bool = False
    delivered: bool = False


def _content(body: dict) -> str:
    value = body.get("content", "")
    if isinstance(value, list):
        return "".join(
            block.get("text", "")
            for block in value
            if isinstance(block, dict) and block.get("type") in ("text", "input_text")
        )
    return value if isinstance(value, str) else ""


@dataclass
class ScanContext:
    saved: dict
    expected: str


def _scan_row(row: dict, context: ScanContext, scan: Scan) -> None:
    saved, expected = context.saved, context.expected
    proof = saved["delivery"]
    payload = row.get("payload", {})
    if proof["tool"] == "codex" and row.get("type") == "session_meta" and isinstance(payload, dict):
        scan.native = (
            payload.get("id") == proof["session"] and payload.get("cwd") == saved["workspace"]
        )
    body = row.get("message", {}) if proof["tool"] in CLAUDE_SHAPED else payload
    if not isinstance(body, dict):
        return
    user = row.get("type") == "user"
    user = (
        user
        if proof["tool"] in CLAUDE_SHAPED
        else row.get("type") == "response_item" and body.get("role") == "user"
    )
    if user and proof["tool"] in CLAUDE_SHAPED:
        scan.native = (
            row.get("sessionId") == proof["session"] and row.get("cwd") == saved["workspace"]
        )
    scan.delivered |= bool(user and scan.native and _content(body) == expected)


def _scan_evidence(saved: dict, expected: str) -> Scan:
    scan = Scan()
    context = ScanContext(saved, expected)
    with safe_path(saved["delivery"]["evidence"]).open() as stream:
        for line in stream:
            if not line.endswith("\n"):
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                _scan_row(row, context, scan)
    return scan


def delivery_evidence(saved: dict) -> None:
    """Ownership is exact native delivery, model judgment belongs to the launcher."""
    if not saved.get("delivery"):
        raise ValueError("no bound delivery; inspect the worker and redispatch")
    expected = safe_path(saved["kickoff"]).read_text().rstrip("\n")
    if digest(saved["kickoff"], kickoff=True) != saved["kickoff_sha256"]:
        raise ValueError("saved kickoff changed")
    if not _scan_evidence(saved, expected).delivered:
        raise ValueError("native delivery does not match the saved worker")
