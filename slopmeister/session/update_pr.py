"""Bound unattended writes to a current, same-repository Dependabot pull request."""

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys

from slopmeister.session import ship

SHA = re.compile(r"[0-9a-f]{40}")
BOT = "app/dependabot"
BLOCKED = (".github", "taskfiles", ".agents", ".claude", ".codex")
ISSUE_MARKER = "<!-- slopmeister-update-prs -->"


@dataclass(frozen=True)
class Target:
    number: int
    expected: str
    repository: str


def _run(repo: Path, *args: str) -> str:
    try:
        return ship.command(repo, *args)
    except ValueError:
        raise ValueError(f"{args[0]} {args[1]} failed") from None


def _gh(repo: Path, repository: str, *args: str) -> str:
    try:
        return ship.gh(repo, repository, *args)
    except ValueError:
        raise ValueError(f"GitHub {args[0]} {args[1]} failed") from None


def _context(workspace: Path) -> tuple[str, str]:
    state = ship.authorized_state(workspace)
    if state.get("commit") != "allow" or state.get("shipping") != "allow":
        raise ValueError("repository has no standing update authority")
    saved = state["ship_target"]["remote"]
    remote = _run(workspace, "git", "remote", "get-url", "--push", "--all", "origin")
    fetch = _run(workspace, "git", "remote", "get-url", "--all", "origin")
    match = ship.GITHUB_REMOTE.fullmatch(remote)
    if not match or remote != fetch or remote != saved:
        raise ValueError("origin differs from the saved GitHub repository")
    repository = match[1]
    info = json.loads(
        _gh(workspace, repository, "repo", "view", "--json", "nameWithOwner,defaultBranchRef")
    )
    if info["nameWithOwner"].lower() != repository.lower():
        raise ValueError("GitHub repository identity changed")
    return repository, info["defaultBranchRef"]["name"]


def _pr(workspace: Path, context: tuple[str, str], target: Target) -> dict:
    repository, base = context
    if (
        type(target.number) is not int
        or target.number < 1
        or not isinstance(target.expected, str)
        or not SHA.fullmatch(target.expected)
        or target.repository.lower() != repository.lower()
    ):
        raise ValueError("pull request is not the exact open same-repository bot head")
    fields = "number,url,state,author,baseRefName,headRefName,headRefOid,headRepository"
    row = json.loads(_gh(workspace, repository, "pr", "view", str(target.number), "--json", fields))
    valid = (
        row.get("number") == target.number
        and row.get("state") == "OPEN"
        and row.get("author", {}).get("login") == BOT
        and row.get("baseRefName") == base
        and row.get("headRefOid") == target.expected
        and row.get("headRepository", {}).get("nameWithOwner", "").lower() == repository.lower()
        and row.get("headRefName", "").startswith("dependabot/")
        and row.get("url") == f"https://github.com/{repository}/pull/{target.number}"
    )
    if not valid:
        raise ValueError("pull request is not the exact open same-repository bot head")
    return row


def _candidate(workspace: Path, source: Path, expected: str) -> str:
    if source.is_symlink() or not source.is_dir() or source.resolve() == workspace.resolve():
        raise ValueError("source must be a separate regular directory")
    _run(workspace, "git", "fetch", "--no-tags", str(source.resolve()), "HEAD")
    sha = _run(workspace, "git", "rev-parse", "FETCH_HEAD")
    if not SHA.fullmatch(sha):
        raise ValueError("fetched commit identifier is invalid")
    _run(workspace, "git", "merge-base", "--is-ancestor", expected, sha)
    changed = _run(
        workspace, "git", "diff", "--no-renames", "--name-only", "-z", expected, sha, "--"
    )
    if any(
        (name := path.rsplit("/", 1)[-1].casefold()) == ".mcp.json"
        or re.fullmatch(r"taskfile(?:[.]dist)?[.]ya?ml", name)
        or (name.endswith(".md") and name.startswith(("agents.", "claude.")))
        or any(part.casefold() in BLOCKED for part in path.split("/"))
        for path in changed.split("\0")
    ):
        raise ValueError("fix changes a gate, workflow or delivered configuration")
    return sha


def push(workspace: Path, source: Path, target: Target) -> dict:
    workspace = workspace.resolve()
    context = _context(workspace)
    pr = _pr(workspace, context, target)
    branch = pr["headRefName"]
    if ship.remote_sha(workspace, branch) != target.expected:
        raise ValueError("remote bot head changed before push")
    sha = _candidate(workspace, source, target.expected)
    if sha == target.expected:
        return {"pr": pr["url"], "sha": sha, "pushed": False}
    ref = f"refs/heads/{branch}"
    _run(
        workspace, "git", "-c", "core.hooksPath=/dev/null", "push", "--no-verify",
        "--no-follow-tags", "--no-recurse-submodules", "origin", f"{sha}:{ref}",
    )  # fmt: skip
    if ship.remote_sha(workspace, branch) != sha:
        raise ValueError("pushed bot head is unconfirmed")
    return {"pr": pr["url"], "sha": sha, "pushed": True}


def _existing_issue(workspace: Path, repository: str) -> str | None:
    owner = _run(workspace, "gh", "api", "user", "--jq", ".login")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", owner):
        raise ValueError("authenticated GitHub login is invalid")
    options = ("--state", "open", "--limit", "1000", "--json", "number,url,body,author")
    raw = _gh(workspace, repository, "issue", "list", *options)
    issues = json.loads(raw)
    if not isinstance(issues, list) or len(issues) >= 1000:
        raise ValueError("open issue inventory is incomplete")
    marked = [
        row
        for row in issues
        if isinstance(row, dict)
        and isinstance(row.get("author"), dict)
        and row["author"].get("login", "").casefold() == owner.casefold()
        and ISSUE_MARKER in (row.get("body") or "")
    ]
    if len(marked) > 1:
        raise ValueError("multiple open update issues require operator inspection")
    return marked[0]["url"] if marked else None


def _row(workspace: Path, context: tuple[str, str], item: dict) -> str:
    if not isinstance(item, dict) or set(item) - {"number", "head", "ci", "smoke", "fix"}:
        raise ValueError("update row has an invalid shape")
    number, head = item.get("number"), item.get("head")
    pr = _pr(workspace, context, Target(number, head, context[0]))
    ci, smoke = item.get("ci"), item.get("smoke")
    if ci not in ("pass", "fail", "pending") or smoke not in ("pass", "fail", "pending"):
        raise ValueError("update row has an invalid test state")
    fix = item.get("fix")
    if fix is not None and (not isinstance(fix, str) or not SHA.fullmatch(fix) or fix != head):
        raise ValueError("update row has an invalid fix identifier")
    status = (
        "ready" if ci == smoke == "pass" else "needs fix" if "fail" in (ci, smoke) else "unverified"
    )
    reason = ", ".join(
        f"{name} failed" for name, value in (("CI", ci), ("smoke", smoke)) if value == "fail"
    )
    if fix:
        reason = (reason + "; " if reason else "") + f"fix pushed {fix}"
    assessment = status + (": " + reason if reason else "")
    return f"| [#{number}]({pr['url']}) | `{head}` | {ci} | {smoke} | {assessment} |"


def _body(workspace: Path, context: tuple[str, str], rows: list[dict]) -> str:
    if not isinstance(rows, list) or not 0 < len(rows) <= 50:
        raise ValueError("update batch must contain 1 to 50 PRs")
    lines = [_row(workspace, context, row) for row in rows]
    if len({row["number"] for row in rows}) != len(rows):
        raise ValueError("update batch contains duplicate PRs")
    return (
        f"Mode: spine\n\n{ISSUE_MARKER}\n\n## Outcome\n\n"
        "Validate and finish the listed dependency updates. "
        "Merge and deployment require operator action.\n\n"
        "## Current state\n\n"
        "| PR | Exact head | CI | Local smoke | Assessment |\n"
        "|---|---|---|---|---|\n" + "\n".join(lines) + "\n\n## Acceptance\n\n"
        "1. `task check` passes for each final PR head.\n"
        "2. The worker runs the target's component checks and records their result.\n"
        "3. No PR is merged or deployed without operator action.\n"
    )


def publish(workspace: Path, repository: str, rows: list[dict]) -> dict:
    workspace = workspace.resolve()
    context = _context(workspace)
    if repository.lower() != context[0].lower():
        raise ValueError("issue target differs from saved repository")
    existing = _existing_issue(workspace, repository)
    if existing:
        return {"issue": existing, "created": False}
    body = _body(workspace, context, rows)
    url = _gh(
        workspace,
        repository,
        "issue",
        "create",
        "--title=Dependency update review",
        "--body=" + body,
    )
    prefix = f"https://github.com/{repository}/issues/"
    number = url.removeprefix(prefix)
    if not url.startswith(prefix) or not number.isdecimal():
        raise ValueError("created issue URL is invalid")
    saved = json.loads(
        _gh(workspace, repository, "issue", "view", number, "--json", "number,url,body")
    )
    if saved.get("url") != url or saved.get("body") != body:
        raise ValueError("created issue is unconfirmed")
    return {"issue": url, "created": True}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    action = parser.add_subparsers(dest="action", required=True)
    pushing = action.add_parser("push")
    pushing.add_argument("--cwd", type=Path, required=True)
    pushing.add_argument("--source", type=Path, required=True)
    pushing.add_argument("--pr", type=int, required=True)
    pushing.add_argument("--repository", required=True)
    pushing.add_argument("--expected-head", required=True)
    issuing = action.add_parser("issue")
    issuing.add_argument("--cwd", type=Path, required=True)
    issuing.add_argument("--repository", required=True)
    issuing.add_argument("--report-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = (
            push(args.cwd, args.source, Target(args.pr, args.expected_head, args.repository))
            if args.action == "push"
            else publish(args.cwd, args.repository, json.loads(args.report_file.read_text()))
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"UPDATE BLOCKED: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0
