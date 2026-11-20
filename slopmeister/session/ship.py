"""Ship one declared task branch: push it and, unless push-only, open or update its GitHub PR.

Git and GitHub are the state. A rerun pushes only when the remote branch differs from HEAD and
writes the PR only when its title or body differ, so a confirmed write is never repeated. The
push-only mode works on any forge and pushes HEAD to the branch recorded at launch.
"""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from slopmeister.session import git_environment, repositories

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
REVIEW_TRACE = re.compile(r"^[^A-Za-z\n]*independent\W+review\b", re.M | re.I)
GITHUB_REMOTE = re.compile(
    "(?:git@github\\.com:|https://github\\.com/)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\\.git)?"
)
# A SemVer pre-release such as 0.2.1-dev1. A release tag without a suffix keeps native approval.
PRE_RELEASE_TAG = re.compile(r"v?\d+\.\d+\.\d+-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*")
DEFAULT_BRANCH = re.compile(r"ref: refs/heads/(\S+)\tHEAD")
PR_FIELDS = "number,url,state,body,title,baseRefName,headRefName,headRefOid,headRepository,mergedAt"


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


def ship_target(repo, state, body, review_in_notes=False):
    if command(repo, "git", "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("commit the explicit task files before shipping")
    if review_in_notes and REVIEW_TRACE.search(body):
        raise ValueError("keep independent review in the notes and handoff, outside the PR body")
    if not review_in_notes and len(REVIEW_LINE.findall(body)) != 1:
        raise ValueError("PR body requires exactly one independent-review line")
    remote = command(repo, "git", "remote", "get-url", "--push", "--all", "origin")
    match = GITHUB_REMOTE.fullmatch(remote)
    fetch = command(repo, "git", "remote", "get-url", "--all", "origin")
    if not match or remote != state["ship_target"]["remote"] or fetch != remote:
        raise ValueError("origin is not the saved single GitHub repository, see --push-only")
    branch = command(repo, "git", "branch", "--show-current")
    if state["ship_target"].get("push", branch) != branch:
        raise ValueError("the recorded push branch differs from the task branch, use --push-only")
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


def push(repo, branch, sha, source=None):
    ref = f"refs/heads/{branch}"
    # Explicit flags, so repository config such as push.followTags cannot add refs to the push.
    flags = ("--no-follow-tags", "--no-recurse-submodules")
    flags += () if source else ("--set-upstream",)
    command(repo, "git", "push", *flags, "origin", f"{source or ref}:{ref}")
    if remote_sha(repo, branch) != sha:
        raise ValueError("pushed SHA is unconfirmed")


def push_target(repo, state):
    saved = state["ship_target"]
    remote = command(repo, "git", "remote", "get-url", "--push", "--all", "origin")
    fetch = command(repo, "git", "remote", "get-url", "--all", "origin")
    # A second URL would receive the push while the default-branch check reads only the first.
    if "\n" in remote or remote != saved["remote"] or fetch != remote:
        raise ValueError("origin is not the saved single repository")
    if command(repo, "git", "branch", "--show-current") != saved["branch"]:
        raise ValueError("current task branch changed or HEAD is detached")
    target = saved.get("push", saved["branch"])
    default = DEFAULT_BRANCH.match(command(repo, "git", "ls-remote", "--symref", "origin", "HEAD"))
    if not default or default[1] == target:
        raise ValueError("the remote default branch is unknown or is the push branch")
    return target


def remote_tag(repo, ref):
    remote = command(repo, "git", "ls-remote", "origin", ref)
    return next(
        (line.split()[0] for line in remote.splitlines() if line.endswith("\t" + ref)), None
    )


def check_tag(repo, tag, sha):
    ref = f"refs/tags/{tag}"
    if not PRE_RELEASE_TAG.fullmatch(tag):
        raise ValueError("only a pre-release version tag such as 0.2.1-dev1 may be pushed")
    if command(repo, "git", "rev-parse", "--verify", "--end-of-options", ref + "^{commit}") != sha:
        raise ValueError("the tag does not point at HEAD")
    local = command(repo, "git", "rev-parse", "--verify", "--end-of-options", ref)
    if remote_tag(repo, ref) not in (None, local):
        raise ValueError("the remote tag exists at another object and is never moved")
    return ref, local


def push_only(repo, tag=None):
    target = push_target(repo, authorized_state(repo))
    sha = command(repo, "git", "rev-parse", "HEAD")
    ref, local = check_tag(repo, tag, sha) if tag else (None, None)
    current = remote_sha(repo, target)
    # A wrong or missing recorded branch would otherwise create a stray branch without approval.
    if current is None:
        raise ValueError(f"origin has no branch {target}, create it once with an approved git push")
    pushed = current != sha
    if pushed:
        push(repo, target, sha, source=sha)
    result = dict(sha=sha, branch=target, pushed=pushed)
    if tag:
        result.update(tag=tag, tag_pushed=remote_tag(repo, ref) is None)
        if result["tag_pushed"]:
            flags = ("--no-follow-tags", "--no-recurse-submodules")
            command(repo, "git", "push", *flags, "origin", f"{ref}:{ref}")
            if remote_tag(repo, ref) != local:
                raise ValueError("pushed tag is unconfirmed")
    return result


def open_pr(repo, target):
    fields = ("--head", target["branch"], "--state", "all", "--limit", "1000", "--json", PR_FIELDS)
    rows = json.loads(gh(repo, target["repository"], "pr", "list", *fields))
    for row in rows:
        if (
            row["state"] not in ("OPEN", "MERGED")
            or row["baseRefName"] != target["base"]
            or row["headRefName"] != target["branch"]
            or row["headRepository"]["nameWithOwner"].lower() != target["repository"].lower()
        ):
            raise ValueError("existing PR does not match the saved repository and open task branch")
    opened = [row for row in rows if row["state"] == "OPEN"]
    if len(opened) > 1:
        raise ValueError("multiple PRs for this task branch")
    merged = [row for row in rows if row["state"] == "MERGED"]
    predecessor = max(merged, key=lambda row: (row["mergedAt"], row["number"])) if merged else None
    return (opened[0] if opened else None), predecessor


def check_follow_up(repo, pr, predecessor, sha, body):
    if not predecessor:
        return
    line = f"Follows #{predecessor['number']}"
    if re.findall(r"^Follows #\d+$", body, re.M) != [line]:
        raise ValueError("PR body requires exactly one predecessor line: " + line)
    if pr:
        return
    previous = predecessor["headRefOid"]
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", previous):
        raise ValueError("invalid merged PR head")
    if previous == sha:
        raise ValueError("no follow-up commits")
    try:
        command(repo, "git", "merge-base", "--is-ancestor", previous, sha)
    except ValueError:
        raise ValueError(
            "HEAD does not descend from the merged PR head, or that head is missing"
        ) from None


def write_pr(repo, target, text, sha):
    title, body = text
    pr, predecessor = open_pr(repo, target)
    check_follow_up(repo, pr, predecessor, sha, body)
    if pr and pr["title"] == title and pr["body"] == body:
        return pr, "unchanged"
    action = "updated" if pr else "created"
    head = ["edit", str(pr["number"])] if pr else ["create", "--head", target["branch"]]
    base = [] if pr else ["--base", target["base"]]
    gh(repo, target["repository"], "pr", *head, *base, "--title=" + title, "--body=" + body)
    pr, _ = open_pr(repo, target)
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


def ship(repo, title, body, review_in_notes=False):
    target = ship_target(repo, authorized_state(repo), body, review_in_notes)
    sha = command(repo, "git", "rev-parse", "HEAD")
    pr, predecessor = open_pr(repo, target)
    check_follow_up(repo, pr, predecessor, sha, body)
    pushed = remote_sha(repo, target["branch"]) != sha
    if pushed:
        push(repo, target["branch"], sha)
    pr, action = write_pr(repo, target, (title, body), sha)
    merge = mergeability(repo, target["repository"], pr["number"])
    return dict(pr=pr["url"], sha=sha, pushed=pushed, pr_action=action, mergeable=merge)


def entry_workspace() -> Path:
    path = Path(sys.argv[0]).resolve()
    if path.parts[-4:] != ("skills", "ship", "scripts", "ship.py"):
        raise ValueError("use the session's fixed shipping helper")
    return path.parents[4]


def check_session_target(repo: Path) -> None:
    owner = entry_workspace()
    if owner == repo:
        return
    if not repositories.read(owner).get("repositories"):
        raise ValueError("shipping helper cannot target a repository outside its session")
    rows = repositories.members(owner)
    member = next((row for row in rows if row["worktree"] == str(repo)), None)
    if member is None or repositories.read(repo).get("session") != str(owner):
        raise ValueError("shipping helper cannot target a repository outside its session")
    if (member["commit"], member["shipping"]) != (rows[0]["commit"], rows[0]["shipping"]):
        raise ValueError("repository permissions differ from this helper's native approval route")


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--push-only", action="store_true")
    parser.add_argument("--tag")
    parser.add_argument("--title")
    parser.add_argument("--body-file", type=Path)
    parser.add_argument("--review-in-notes", action="store_true")
    args = parser.parse_args(argv)
    pr = (args.title, args.body_file, args.review_in_notes or None)
    if args.push_only and any(value is not None for value in pr):
        parser.error("--push-only writes no PR and takes no PR options")
    if not args.push_only and (args.tag or args.title is None or args.body_file is None):
        parser.error("a PR needs --title and --body-file, and --tag needs --push-only")
    try:
        repo = args.cwd.resolve()
        check_session_target(repo)
        if args.push_only:
            result = push_only(repo, args.tag)
        else:
            result = ship(repo, args.title, args.body_file.read_text(), args.review_in_notes)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"SPINE BLOCKED: shipping: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0
