"""Attach another repository using a running session's existing plot and approval policy."""

import argparse
import fcntl
from pathlib import Path
import re
import shlex
import subprocess

from slopmeister import removal
from slopmeister.claims import evidence
from slopmeister.errors import SlopmeisterError
from slopmeister.install.check import CheckContext, check
from slopmeister.install.models import InstallRequest
from slopmeister.install.payload import declaration
from slopmeister.install.preflight import (
    GitOptions,
    configuration_roots,
    protected,
    reject_git_context,
    safe_path,
)
from slopmeister.install.preflight import git as install_git
from slopmeister.install.prepare import prepare
from slopmeister.install.snapshot import source_identity
from slopmeister.install.workspace import record_push_branch
from slopmeister.session import launch_identity
from slopmeister.session import repositories as saved
from slopmeister.slots import allocation, claimed, leftover
from slopmeister.threads import occupants


def validate(repo: Path, name: str, destination: Path) -> Path:
    repo = repo.expanduser().absolute()
    safe_path(repo)
    safe_path(destination)
    common = Path(saved.git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    if common != repo / ".git":
        raise ValueError("name the repository's main checkout")
    if destination.exists():
        raise ValueError(f"repository destination already exists: {destination}")
    if saved.git(repo, "for-each-ref", f"refs/heads/{name}"):
        raise ValueError(f"task branch already exists in {repo}")
    return repo


def _push_branches(launch) -> None:
    if not launch.push_branches:
        return
    if launch.directory or launch.abandon:
        raise ValueError("--push-branch needs a repository session and is not taken with --abandon")
    named = [launch.repo, *(Path(value).expanduser() for value in launch.repositories)]
    if set(launch.push_branches) - {str(path.resolve()) for path in named}:
        reason = "--push-branch names a repository outside this launch"
        if launch.redispatch:
            reason += (
                "; for an existing companion use repository add --workspace <primary> "
                "--repo <main-checkout> --push-branch <branch>"
            )
        raise ValueError(reason)


def preflight(launch) -> None:
    _push_branches(launch)
    if not launch.repositories:
        return
    if launch.directory or launch.redispatch or launch.abandon or launch.tool == "opencode":
        raise ValueError("--repository requires a fresh Claude or Codex repository session")
    seen = {str(launch.repo.resolve())}
    names = set()
    primary = launch.repo / ".worktrees" / launch.name
    for value in launch.repositories:
        repo = Path(value).expanduser().absolute()
        if str(repo) in seen or repo.name in names:
            raise ValueError("duplicate repository or companion name")
        validate(repo, launch.name, primary / saved.DIRECTORY / repo.name)
        prepare(InstallRequest("--preflight", launch.plot, str(repo), None, []))
        seen.add(str(repo))
        names.add(repo.name)


def _check_primary(workspace: Path, state: dict) -> None:
    if not state.get("repository_add") or state.get("session"):
        raise ValueError("add repositories from a prepared primary workspace")
    check(CheckContext(workspace, state["plot"], state["commit"], state["grants"]))
    identity = launch_identity.path(workspace)
    if (
        identity.exists()
        and launch_identity.private_json(identity, "launcher identity").get("tool") == "opencode"
    ):
        raise ValueError("OpenCode does not support adding repositories")


def _refuse_delivery(reason: str, workspace: Path, repo: Path, push: str | None) -> None:
    command = [
        "bin/slopmeister",
        "repository",
        "add",
        "--workspace",
        str(workspace),
        "--repo",
        str(repo),
    ]
    if push is not None:
        command += ["--push-branch", push]
    raise ValueError(
        f"{reason}. Use an existing checkout matching the launch source and permissions. "
        "If none is available, preserve this worktree and hand off to one newly named worker "
        "with all repositories under the approved plot. See docs/launcher-recovery.md.\n"
        f"Retry from a matching checkout: {shlex.join(command)}"
    )


def _request(workspace: Path, repo: Path, state: dict, push: str | None) -> InstallRequest:
    root, declared = declaration(state["plot"])
    target = declared["target"]
    policy = target["repository"]
    shipping = "deny" if state.get("proof_owner") else policy.get("shipping", "deny")
    reason = ""
    if (policy["commit"], shipping, target.get("service_actions", [])) != (
        state["commit"],
        state["shipping"],
        state.get("service_actions", []),
    ):
        reason = "plot permissions changed"
    elif state.get("source_identity") != source_identity(root):
        reason = "session delivery differs"
    if reason:
        _refuse_delivery(reason, workspace, repo, push)
    return InstallRequest(
        "--preflight",
        state["plot"],
        str(repo),
        None,
        state["grants"],
        proof_owner=state.get("proof_owner"),
        session=str(workspace),
        push_branch=push,
    )


def _attach(workspace: Path, repo: Path, state: dict, push: str | None) -> dict:
    _check_primary(workspace, state)
    rows = saved.members(workspace)
    for row in rows:
        if row["repository"] != str(repo):
            continue
        if row == rows[0] or push is None:
            raise ValueError("repository already belongs to this session")
        child = Path(row["worktree"])
        member = saved.read(child)
        check(CheckContext(child, state["plot"], state["commit"], state["grants"]))
        record_push_branch(child, saved.state_path(child).parent, member, push)
        return row | {"updated_push": push}

    request = _request(workspace, repo, state, push)
    destination = workspace / saved.DIRECTORY / repo.name
    validate(repo, rows[0]["branch"], destination)
    prepare(request)
    pending = dict(
        repository=str(repo),
        worktree=str(destination),
        branch=rows[0]["branch"],
        plot=state["plot"],
        commit=state["commit"],
        shipping=state["shipping"],
        status="pending",
    )
    state["repositories"] = [*rows, pending]
    path = saved.state_path(workspace)
    saved.save(path, state)
    member = _create_member(repo, destination, request, state, path)
    state["repositories"][-1] = saved.record(destination, member)
    saved.save(path, state)
    return state["repositories"][-1]


def _rollback_member(repo: Path, destination: Path, branch: str, start: str) -> bool:
    try:
        if saved.git(repo, "rev-parse", "--revs-only", f"refs/heads/{branch}") != start or any(
            process.inside for process in occupants.census(str(destination))
        ):
            return False
        baseline = (
            start or install_git(destination, ("mktree",), GitOptions(data=b"")).decode().strip()
        )
        entries = install_git(destination, ("ls-tree", "-rz", baseline)).split(b"\0")
        roots = [*configuration_roots(entries), removal.SCRATCH]
        changed = install_git(destination, ("diff", "--name-only", "--no-renames", "-z", baseline))
        other = install_git(destination, ("ls-files", "--others", "-z"))
        if any(
            not protected(name.decode(), roots) for name in (changed + other).split(b"\0") if name
        ):
            return False
        install_git(
            repo, ("worktree", "remove", "--force", str(destination)), GitOptions(optional=True)
        )
        if destination.exists():
            removal.remove_tree(destination)
        saved.git(repo, "worktree", "prune")
        if start:
            saved.git(repo, "update-ref", "-d", f"refs/heads/{branch}", start)
        return True
    except OSError, ValueError, SlopmeisterError, subprocess.SubprocessError:
        return False


def _start(repo: Path) -> str:
    if "origin" not in saved.git(repo, "remote").splitlines():
        return saved.git(repo, "rev-parse", "--revs-only", "HEAD^{commit}")
    try:
        advertised = saved.git(repo, "ls-remote", "--symref", "origin", "HEAD")
        match = re.search(r"^ref: (refs/heads/[^\s]+)\tHEAD$", advertised, re.M)
        if not match:
            if (
                not advertised
                and not saved.git(repo, "rev-parse", "--revs-only", "HEAD^{commit}")
                and not saved.git(repo, "ls-remote", "origin")
            ):
                return ""
            raise ValueError("origin does not advertise a default branch")
        ref = match[1]
        saved.git(repo, "check-ref-format", ref)
        tracking = "refs/remotes/origin/" + ref.removeprefix("refs/heads/")
        saved.git(repo, "fetch", "--quiet", "--no-tags", "origin", f"+{ref}:{tracking}")
        return saved.git(repo, "rev-parse", "--verify", f"{tracking}^{{commit}}")
    except (ValueError, subprocess.SubprocessError) as error:
        raise ValueError(f"cannot select companion start in {repo}: {error}") from error


def _create_member(repo, destination, request, state, path) -> dict:
    rows = state["repositories"][:-1]
    branch = rows[0]["branch"]
    start, created = "", False
    try:
        start = _start(repo)
        options = (
            ["--no-track", "-b", branch, str(destination), start]
            if start
            else ["--orphan", "-b", branch, str(destination)]
        )
        saved.git(repo, "worktree", "add", "--quiet", *options)
        created = True
        request.action, request.workspace = "--prepare", str(destination)
        prepare(request)
        member = saved.read(destination)
        # Preparation reads the plot again after a possibly slow origin fetch.
        if any(
            member.get(key, []) != state.get(key, [])
            for key in ("commit", "shipping", "service_actions")
        ):
            _refuse_delivery(
                "plot permissions changed", Path(state["worktree"]), repo, request.push_branch
            )
        if member["source_root"] != state.get("source_root") and member[
            "source_identity"
        ] != state.get("source_identity"):
            _refuse_delivery(
                "session delivery differs", Path(state["worktree"]), repo, request.push_branch
            )
        return member
    except BaseException:
        cleared = (
            _rollback_member(repo, destination, branch, start)
            if created
            else (
                not destination.exists()
                and not destination.is_symlink()
                and not saved.git(repo, "for-each-ref", f"refs/heads/{branch}")
            )
        )
        if cleared:
            state["repositories"] = rows
            saved.save(path, state)
        raise


def add(workspace: Path, repo: Path, push: str | None = None) -> dict:
    reject_git_context()
    workspace = workspace.absolute()
    safe_path(workspace)
    path = saved.state_path(workspace)
    with (path.parent / "repositories.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _attach(workspace, repo.expanduser().absolute(), saved.read(workspace), push)


def _companions(path: Path) -> list[dict]:
    state_path = saved.state_path(path)
    if not state_path.is_file() or "repositories" not in evidence.read(state_path):
        return []
    return saved.members(path)[1:]


def check_companions(path: Path, force: bool) -> list[dict]:
    children = _companions(path)
    for row in children:
        child, repo = Path(row["worktree"]), Path(row["repository"])
        if saved.read(child).get("allocation") or (child / allocation.ALLOCATION).exists():
            raise SlopmeisterError("companion has a separate slot; preserve it for its owner")
        claimed.refuse(child, row["plot"], repo)
        removal.clean(child, repo, force)
        if not force:
            removal.ignored_work(child)
        if any(process.inside for process in occupants.census(str(child))):
            raise SlopmeisterError(f"a worker still occupies {child}, refusing")
        removal.nested(child)
    return children


def remove_companions(path: Path) -> None:
    children = _companions(path)
    if not children:
        return
    state = saved.read(path)
    for row in reversed(children):
        child, repo = Path(row["worktree"]), Path(row["repository"])
        leftover.remove(child, "retry removal of the primary workspace", repo)
        state["repositories"].remove(row)
        saved.save(saved.state_path(path), state)
        print(f"companion removed: {child}; branch kept")


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("add", "status"))
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--push-branch")
    args = parser.parse_args(argv)
    try:
        if args.action == "add":
            if args.repo is None:
                parser.error("add requires --repo")
            row = add(args.workspace, args.repo, args.push_branch)
            if "updated_push" in row:
                print(
                    f"repository push branch updated: {row['worktree']} push={row['updated_push']}"
                )
                return 0
            print(f"repository added: {row['worktree']} (branch {row['branch']})")
            print(f"plot {row['plot']}: commit={row['commit']}, shipping={row['shipping']}")
            print(f"Read {row['worktree']}/AGENTS.md or CLAUDE.md before editing this member.")
        else:
            for row in saved.members(args.workspace.absolute()):
                push = saved.read(Path(row["worktree"]))["ship_target"].get("push", row["branch"])
                permissions = f"commit={row['commit']} shipping={row['shipping']}"
                print(f"{row['worktree']} {permissions} push={push}")
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"repository: {error}")
        return 1
    return 0
