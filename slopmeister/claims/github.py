"""GitHub transport and repository identity for issue claims."""

from collections.abc import Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess

from slopmeister.plots import load_all
from slopmeister.session import git_environment
from slopmeister.threads.occupants import printable

ROOT = Path(__file__).resolve().parents[2]
CLAIM = "agent:claimed"
ACTIVE = {"pending", "claimed", "abandoning", "closing"}
DETAIL_LIMIT = 200


@dataclass(frozen=True)
class Repository:
    root: Path
    common: Path
    name: str
    remote: str
    plot: str


@dataclass(frozen=True)
class Request:
    endpoint: str
    method: str = "GET"
    payload: object | None = None


def detail(stderr: str) -> str:
    """The first line a failed child printed, safe to show: no URL credentials, bounded."""
    line = next((row.strip() for row in stderr.splitlines() if row.strip()), "")
    line = re.sub(r"://[^/\s]*@", "://", line)
    return ": " + printable(line)[:DETAIL_LIMIT] if line else ""


def command(args: Sequence[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        args, cwd=cwd, text=True, capture_output=True, timeout=30, env=git_environment.child()
    )
    if result.returncode:
        failure = f"{Path(args[0]).name} operation failed ({result.returncode})"
        raise ValueError(failure + detail(result.stderr))
    return result.stdout.strip()


def issue_number(value: object) -> int:
    valid = isinstance(value, str | int) and not isinstance(value, bool)
    if not valid or not re.fullmatch("[1-9][0-9]*", str(value)):
        raise ValueError("issue identifier must be a positive integer")
    return int(value)


def repository_name(remote: str) -> str:
    prefix = r"(?:git@github\.com:|https://github\.com/)"
    part = r"[A-Za-z0-9_-][A-Za-z0-9_.-]*"
    match = re.fullmatch(rf"{prefix}({part}/{part}?)(?:\.git)?", remote)
    if not match:
        raise ValueError("one explicit GitHub origin is required")
    return match[1].lower()


def git(root: Path, *args: str) -> str:
    if git_environment.redirect():
        raise ValueError("Git context overrides are not allowed for issue management")
    return command(["git", "-C", str(root), *args])


def declaration(plot: str) -> dict:
    directory = Path(os.environ.get("PLOT_DECLARATIONS", str(ROOT / "plots")))
    values = load_all(directory)
    if plot not in values or "target" not in values[plot]:
        raise ValueError("undeclared issue-management plot")
    return values[plot]["target"]


def context(root: Path, plot: str) -> Repository:
    top = Path(git(root, "rev-parse", "--show-toplevel")).resolve()
    remote = git(top, "remote", "get-url", "--all", "origin")
    push = git(top, "remote", "get-url", "--push", "--all", "origin")
    if remote != push:
        raise ValueError("origin fetch and push destinations disagree")
    common = Path(git(top, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    return Repository(top, common, repository_name(remote), remote, plot)


def request(ctx: Repository, call: Request) -> object | None:
    args = ["gh", "api", "--hostname", "github.com", "-X", call.method]
    args.append(f"repos/{ctx.name}/{call.endpoint}")
    if call.payload is not None:
        args += ["--input", "-"]
    source = json.dumps(call.payload) if call.payload is not None else None
    result = subprocess.run(
        args, input=source, text=True, capture_output=True, timeout=30, env=git_environment.child()
    )
    if result.returncode:
        failure = f"GitHub {call.method} failed ({result.returncode})"
        raise ValueError(failure + detail(result.stderr))
    return json.loads(result.stdout) if result.stdout.strip() else None


def pages(ctx: Repository, endpoint: str) -> list[dict]:
    values = []
    for page in range(1, 1001):
        separator = "&" if "?" in endpoint else "?"
        rows = request(ctx, Request(f"{endpoint}{separator}per_page=100&page={page}"))
        if not isinstance(rows, list):
            raise ValueError("incomplete GitHub list response")
        values.extend(rows)
        if len(rows) < 100:
            return values
    raise ValueError("GitHub pagination limit reached; inventory incomplete")


def labels(item: dict) -> list[str]:
    if item.get("state") not in ("open", "closed") or not isinstance(item.get("labels"), list):
        raise ValueError("invalid GitHub issue state")
    names = [value.get("name") if isinstance(value, dict) else value for value in item["labels"]]
    if any(not isinstance(value, str) for value in names):
        raise ValueError("invalid GitHub issue labels")
    return names


def remote_issue(ctx: Repository, number: int) -> dict:
    item = request(ctx, Request(f"issues/{issue_number(number)}"))
    if not isinstance(item, dict) or item.get("number") != number or "pull_request" in item:
        raise ValueError("GitHub response is not the exact issue")
    labels(item)
    return item


def workspaces(ctx: Repository) -> list[Path]:
    output = git(ctx.root, "worktree", "list", "--porcelain")
    return [
        Path(line[9:]).resolve() for line in output.splitlines() if line.startswith("worktree ")
    ]
