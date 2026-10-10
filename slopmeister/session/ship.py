"""Ship one declared task branch: push it and open or update its one GitHub PR.

Git and GitHub are the state. A rerun pushes only when the remote branch differs from HEAD and
writes the PR only when its title or body differ, so a confirmed write is never repeated.
"""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from slopmeister.session import git_environment

COMMAND_TIMEOUT_SECONDS = 90
MERGEABILITY_READS = 5
MERGEABILITY_INTERVAL_SECONDS = 2
ALLOWED_GIT_ENV = (
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_NOSYSTEM",
    "GIT_EDITOR",
    "GIT_PAGER",
    "GIT_TERMINAL_PROMPT",
)
REVIEW_LINE = re.compile("^Independent review: (?:PASS|PENDING|N/A) - .+$", re.M)
GITHUB_REMOTE = re.compile(
    "(?:git@github\\.com:|https://github\\.com/)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\\.git)?"
)
PR_FIELDS = "number,url,state,body,title,baseRefName,headRefName,headRepository"


def command(repo, *args):
    try:
        result = subprocess.run(
            args,
            cwd=repo,
            text=True,
            capture_output=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            env=git_environment.child(),
        )
    except subprocess.TimeoutExpired:
        # The full argv would carry the PR body, name only the command.
        raise ValueError(
            f"{' '.join(args[:3])} timed out after {COMMAND_TIMEOUT_SECONDS}s"
        ) from None
    if result.returncode:
        raise ValueError(
            f"{' '.join(args[:3])} failed ({result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout.strip()


def gh(repo, repository, *args):
    pinned = "github.com/" + repository
    scope = [pinned] if args[:2] == ("repo", "view") else ["--repo", pinned]
    return command(repo, "gh", *args, *scope)


def authorized_state(repo):
    overrides = sorted(key for key in os.environ if key.startswith("GIT_"))
    overrides = [
        key for key in overrides if key not in ALLOWED_GIT_ENV and not git_environment.injected(key)
    ]
    if overrides:
        raise ValueError("shipping refuses Git context overrides: " + ", ".join(overrides))
    directory = Path(command(repo, "git", "rev-parse", "--absolute-git-dir")) / "slopmeister-config"
    state = json.loads((directory / "state.json").read_text())
    if state["worktree"] != str(repo):
        raise ValueError("saved repository identity differs")
    permissions = (state.get("commit"), state.get("shipping"))
    if state.get("directory") or any(value not in ("allow", "deny") for value in permissions):
        raise ValueError("repository shipping declaration is missing or invalid")
    command(repo, sys.executable, str(directory / "config-install.py"), "--verify-shipping")
    roots = [":(literal)" + root for root in state["roots"]]
    if command(repo, "git", "diff", "--name-only", state["baseline"], "HEAD", "--", *roots):
        raise ValueError("delivered session configuration changed in the commit being shipped")
    return state


def ship_target(repo, state, body):
    if command(repo, "git", "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("commit the explicit task files before shipping")
    if len(REVIEW_LINE.findall(body)) != 1:
        raise ValueError("PR body requires exactly one independent-review line")
    remote = command(repo, "git", "remote", "get-url", "--push", "--all", "origin")
    match = GITHUB_REMOTE.fullmatch(remote)
    fetch = command(repo, "git", "remote", "get-url", "--all", "origin")
    if not match or remote != state["ship_target"]["remote"] or fetch != remote:
        raise ValueError("origin is not the saved single GitHub repository")
    branch = command(repo, "git", "branch", "--show-current")
    view = gh(repo, match[1], "repo", "view", "--json", "nameWithOwner,defaultBranchRef")
    info = json.loads(view)
    base = info["defaultBranchRef"]["name"]
    if info["nameWithOwner"].lower() != match[1].lower() or branch == base:
        raise ValueError("repository differs or the task branch is the default branch")
    if branch != state["ship_target"]["branch"]:
        raise ValueError("current task branch changed or HEAD is detached")
    return dict(repository=match[1], branch=branch, base=base)


def remote_sha(repo, branch):
    remote = command(repo, "git", "ls-remote", "--heads", "origin", f"refs/heads/{branch}")
    return remote.split()[0] if remote else None


def push(repo, branch, sha):
    ref = f"refs/heads/{branch}"
    # Explicit flags, so repository config such as push.followTags cannot add refs to the push.
    flags = ("--no-follow-tags", "--no-recurse-submodules", "--set-upstream")
    command(repo, "git", "push", *flags, "origin", f"{ref}:{ref}")
    if remote_sha(repo, branch) != sha:
        raise ValueError("pushed SHA is unconfirmed")


def open_pr(repo, target):
    fields = ("--head", target["branch"], "--state", "all", "--json", PR_FIELDS)
    rows = json.loads(gh(repo, target["repository"], "pr", "list", *fields))
    if len(rows) > 1:
        raise ValueError("multiple PRs for this task branch")
    if not rows:
        return None
    row = rows[0]
    if (
        row["state"] != "OPEN"
        or row["baseRefName"] != target["base"]
        or row["headRefName"] != target["branch"]
        or row["headRepository"]["nameWithOwner"].lower() != target["repository"].lower()
    ):
        raise ValueError("existing PR does not match the saved repository and open task branch")
    return row


def write_pr(repo, target, text):
    title, body = text
    pr = open_pr(repo, target)
    if pr and pr["title"] == title and pr["body"] == body:
        return pr, "unchanged"
    action = "updated" if pr else "created"
    head = ["edit", str(pr["number"])] if pr else ["create", "--head", target["branch"]]
    base = [] if pr else ["--base", target["base"]]
    gh(repo, target["repository"], "pr", *head, *base, "--title=" + title, "--body=" + body)
    pr = open_pr(repo, target)
    if not pr or pr["title"] != title or pr["body"] != body:
        raise ValueError("PR write is unconfirmed")
    return pr, action


def mergeability(repo, repository, number):
    for read in range(MERGEABILITY_READS):
        if read:
            time.sleep(MERGEABILITY_INTERVAL_SECONDS)
        try:
            view = gh(repo, repository, "pr", "view", str(number), "--json", "mergeable")
        except ValueError:
            return "UNAVAILABLE"
        state = json.loads(view)["mergeable"]
        if state != "UNKNOWN":
            break
    return state


def ship(repo, title, body):
    target = ship_target(repo, authorized_state(repo), body)
    sha = command(repo, "git", "rev-parse", "HEAD")
    pushed = remote_sha(repo, target["branch"]) != sha
    if pushed:
        push(repo, target["branch"], sha)
    pr, action = write_pr(repo, target, (title, body))
    merge = mergeability(repo, target["repository"], pr["number"])
    return dict(pr=pr["url"], sha=sha, pushed=pushed, pr_action=action, mergeable=merge)


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--title", required=True)
    parser.add_argument("--body-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = ship(args.cwd.resolve(), args.title, args.body_file.read_text())
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"SPINE BLOCKED: shipping: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0
