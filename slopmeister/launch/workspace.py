"""Prepare a worktree or a session directory, and trust the root each tool keys trust on."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess

from slopmeister.install import cli as install
from slopmeister.install.check import state_directory
from slopmeister.install.trust import TrustRequest, trust
from slopmeister.launch.model import REPORT, Launch, Stop, call, die, plain
from slopmeister.paths import vault as selected_vault
from slopmeister.removal import SCRATCH


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def session_root() -> Path:
    return Path(os.environ.get("PLOT_SESSION_ROOT") or Path.home() / ".slopmeister/sessions")


def grants(launch: Launch) -> None:
    """The installer writes grants into each tool's workspace settings, never the launch line."""
    vault = str(selected_vault())
    if not os.path.isdir(vault):
        raise die(f"vault not found at {vault}, set SLOPMEISTER_VAULT")
    granted = [vault]
    if not launch.directory and launch.plot == "slopmeister":
        granted.append(str(launch.repo))
    launch.grants = [item for path in granted for item in ("--grant", path)]


def claude_store(launch: Launch) -> None:
    """A relative CLAUDE_CONFIG_DIR is relative to the directory the session runs in."""
    if "CLAUDE_CONFIG_DIR" not in os.environ:
        launch.claude_root = None
        return
    if not os.environ["CLAUDE_CONFIG_DIR"]:
        raise die(
            "CLAUDE_CONFIG_DIR is empty, refusing to choose a Claude store; "
            "unset it or name a store"
        )
    joined = os.path.join(launch.claude_wt, os.environ["CLAUDE_CONFIG_DIR"])
    launch.claude_root = Path(os.path.realpath(joined))


def _trust_key(launch: Launch) -> str:
    """Claude keys a worktree on its main checkout and a folder on its trusted parent."""
    if not launch.directory:
        common = git(launch.repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
        return os.path.realpath(Path(common.stdout.strip()).parent)
    if launch.tool == "claude":
        return os.path.realpath(session_root())
    return str(launch.wt)


def _store(launch: Launch) -> tuple[Path, str]:
    if launch.tool == "claude":
        return launch.claude_config, "Claude"
    return launch.codex_home / "config.toml", "Codex"


def _trust(launch: Launch, mode: str, failure: str) -> None:
    if launch.tool == "opencode":
        return  # OpenCode keeps no folder trust store.
    store, label = _store(launch)
    request = TrustRequest(mode, store, _trust_key(launch) if mode == "write" else str(launch.wt))
    named = launch.claude_wt if launch.tool == "claude" else launch.wt
    try:
        call(lambda _: trust(request, launch.tool) or 0, [])
    except Stop as error:
        raise die(f"{label} trust entry {failure.format(named)}") from error


def trust_check(launch: Launch) -> None:
    if launch.tool == "claude":
        claude_store(launch)
    _trust(launch, "check", "refused for {}")


def trust_write(launch: Launch) -> None:
    failure = "not written for {}, the working directory exists and the launch did not start"
    _trust(launch, "write", failure)


def _refuse_existing(launch: Launch) -> None:
    repo = launch.repo
    if git(repo, "rev-parse", "--verify", "-q", "HEAD").returncode:
        raise die(f"target repository has no commit yet: {repo}")
    parent = repo / ".worktrees"
    if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
        raise die(
            f"{parent} is a symlink or not a directory, refusing to write through it" + REPORT
        )
    if not git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{launch.name}").returncode:
        raise die(f"branch '{launch.name}' already exists in {repo}, pick a new session name")
    if git(repo, "for-each-ref", f"refs/heads/{launch.name}/").stdout:
        raise die(f"branches exist under '{launch.name}/' in {repo}, pick a new session name")
    if launch.wt.exists():
        raise die(f"worktree path already exists: {launch.wt}, pick a new session name")


def add_worktree(launch: Launch) -> None:
    if launch.repo is None:
        raise die(
            f"target '{launch.plot}' is declared {launch.delivery} and needs a repository path"
        )
    if git(launch.repo, "rev-parse", "--git-common-dir").returncode:
        raise die(f"not a git repository: {launch.repo}")
    launch.wt = launch.repo / ".worktrees" / launch.name
    _refuse_existing(launch)
    launch.claude_wt = launch.repo.resolve() / ".worktrees" / launch.name
    tracked = git(launch.repo, "ls-tree", "--name-only", "HEAD").stdout.lower().splitlines()
    if launch.wt_file_name and launch.wt_file_name.lower() in tracked:
        raise die(
            f"the target tracks {launch.wt_file_name} in HEAD, refusing to copy over it" + REPORT
        )
    trust_check(launch)
    argv = ["worktree", "add", "--quiet", "--no-track"]
    path = f".worktrees/{launch.name}"
    added = subprocess.run(["git", "-C", str(launch.repo), *argv, "-b", launch.name, path])
    if added.returncode:
        raise Stop(added.returncode)


def prepare_worktree(launch: Launch) -> None:
    allocation = [launch.wt_file_name] if launch.wt_file_name else []
    grants(launch)
    call(install.main, ["--preflight", launch.plot, str(launch.repo), *allocation, *launch.grants])
    add_worktree(launch)
    call(install.main, ["--prepare", launch.plot, str(launch.wt), *allocation, *launch.grants])
    trust_write(launch)
    print(f"plot-session: worktree ready at {launch.wt} (branch {launch.name}, plot {launch.plot})")


def prepare_directory(launch: Launch) -> None:
    root = session_root()
    launch.wt = root / launch.name
    probe = root
    while not probe.is_dir():
        probe = probe.parent
    launch.claude_wt = Path(os.path.realpath(probe)) / launch.wt.relative_to(probe)
    grants(launch)
    trust_check(launch)
    call(install.main, ["--directory", launch.plot, str(launch.wt), *launch.grants])
    (launch.wt / f"{launch.name}-NOTES.md").write_bytes(b"")
    trust_write(launch)
    print(
        f"plot-session: session directory ready at {launch.wt} "
        f"(plot {launch.plot}, notes {launch.name}-NOTES.md, vault granted)"
    )


def _registered(launch: Launch) -> None:
    expected = git(launch.repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    actual = git(launch.wt, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if actual.returncode:
        raise die(f"existing workspace is not a registered worktree: {launch.wt}" + REPORT)
    if os.path.realpath(expected.stdout.strip()) != os.path.realpath(actual.stdout.strip()):
        raise die(f"existing workspace belongs to a different repository: {launch.wt}" + REPORT)
    if git(launch.wt, "rev-parse", "--show-toplevel").stdout.strip() != str(launch.claude_wt):
        raise die(f"existing workspace is not the worktree root: {launch.wt}" + REPORT)
    if git(launch.wt, "symbolic-ref", "-q", "HEAD").stdout.strip() != f"refs/heads/{launch.name}":
        raise die(
            f"existing workspace must have branch {launch.name} checked out: {launch.wt}" + REPORT
        )
    records = git(launch.repo, "worktree", "list", "--porcelain", "-z").stdout.split("\0")
    listed = {os.path.realpath(r[9:]) for r in records if r.startswith("worktree ")}
    if str(launch.claude_wt) not in listed:
        raise die(f"existing workspace is not registered: {launch.wt}" + REPORT)


def _output_paths(launch: Launch) -> None:
    """Secondary writes must not undermine adoption's promise to preserve every file."""
    store = _store(launch)[0]
    paths = (launch.state_dir, launch.kickoff_file, launch.command_file, store)
    for index, spelled in enumerate(paths):
        path = os.path.realpath(spelled)
        if os.path.exists(path):
            if index == 0 and not os.path.isdir(path):
                raise plain("redispatch state path is not a directory: " + path + REPORT)
            if index != 0 and not os.path.isfile(path):
                raise plain("redispatch output path is not a regular file: " + path + REPORT)
            if index != 3 and not os.access(path, os.W_OK):
                raise plain("redispatch output path is not writable: " + path + REPORT)
        if os.path.commonpath([str(launch.claude_wt), path]) == str(launch.claude_wt):
            raise plain(
                "redispatch state or trust path lies inside the adopted workspace: " + path + REPORT
            )
        parent = os.path.dirname(path)
        while not os.path.exists(parent):
            parent = os.path.dirname(parent)
        if not os.path.isdir(parent) or not os.access(parent, os.W_OK):
            raise plain("redispatch state or trust parent is not writable: " + parent + REPORT)


def adopt(launch: Launch) -> None:
    """Recovery reads the prepared workspace instead of replaying creation or configuration."""
    if launch.directory:
        root = session_root()
    elif launch.repo is None:
        raise die(
            f"target '{launch.plot}' is declared {launch.delivery} and needs a repository path"
        )
    else:
        root = launch.repo / ".worktrees"
    launch.wt = root / launch.name
    if root.is_symlink() or launch.wt.is_symlink():
        raise die(f"redispatch refuses a symlinked workspace or root: {launch.wt}" + REPORT)
    if not launch.wt.is_dir():
        raise die(f"existing workspace not found: {launch.wt}, redispatch creates nothing")
    launch.claude_wt = launch.wt.resolve()
    if launch.wt_file:
        raise die("redispatch preserves workspace files, do not pass PLOT_SESSION_WORKTREE_FILE")
    if launch.directory and not git(launch.wt, "rev-parse", "--show-toplevel").returncode:
        raise die(f"session directory lies inside a git repository: {launch.wt}" + REPORT)
    if not launch.directory:
        _registered(launch)
    grants(launch)
    call(install.main, ["--check", launch.plot, str(launch.wt), *launch.grants])
    trust_check(launch)
    _output_paths(launch)


def capabilities(launch: Launch) -> None:
    """Use the saved delivery contract; redispatch never upgrades its fixed consumer."""
    directory, _ = state_directory(launch.wt)
    state = json.loads((directory / "state.json").read_text())
    launch.native_server_pins = state.get("native_server_pins", False)
    if type(launch.native_server_pins) is not bool:
        raise die("invalid saved native-server capability")
    if "scratch" not in state:
        return
    if state["scratch"] != SCRATCH:
        raise die("invalid saved scratch ownership")
    path = launch.wt / SCRATCH
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise die("saved session scratch must be a private owned directory")
    launch.scratch = path
