"""Resolve the declared plot, the repository and the machine prerequisites before any mutation."""

from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import shlex
import shutil
import subprocess

from slopmeister.launch.model import REPORT, ROOT, Launch, call, die, plain
from slopmeister.launch.workspace import session_root
from slopmeister.opencode import native
from slopmeister.plots import load_all, query
from slopmeister.workstation.kickoff import MODE_LINES, MODES

DIST = ROOT / "dist"


def _declarations() -> Path:
    return Path(os.environ.get("PLOT_DECLARATIONS") or ROOT / "plots")


def _shape(launch: Launch, default: str) -> None:
    default_root = os.environ.get("HOME", "") + default[1:] if default.startswith("~") else default
    default_worktree = Path(default_root) / ".worktrees" / launch.name if default else None
    worktree_used = bool(
        default_worktree and (default_worktree.exists() or default_worktree.is_symlink())
    )
    prior_directory = session_root() / launch.name
    directory_used = prior_directory.exists() or prior_directory.is_symlink()
    if not launch.repo_arg and not launch.directory_requested:
        if launch.redispatch and directory_used and worktree_used:
            raise die(
                f"both directory and worktree use session name '{launch.name}'; "
                "pass --directory or the repository path with --redispatch"
            )
        if launch.redispatch and directory_used:
            launch.directory_requested = True
        else:
            launch.repo_arg = default
    if not (launch.redispatch or launch.abandon):
        if not launch.directory and directory_used:
            raise die(f"directory session already uses name '{launch.name}'")
        if launch.directory and worktree_used:
            raise die(f"repository worktree already uses name '{launch.name}'")


def policy(launch: Launch) -> None:
    try:
        declared = load_all(_declarations()).get(launch.plot, {})
    except (ValueError, OSError) as error:
        raise plain(str(error)) from error
    target = declared.get("target", {})
    launch.service_actions = bool(target.get("service_actions"))
    repository = target.get("repository", {})
    if launch.tool == "opencode" and repository:
        for permission in ("commit", "shipping"):
            if repository.get(permission, "deny") != "allow":
                raise die(
                    f"OpenCode cannot enforce this plot's Git policy: {permission} permission "
                    "is deny; use Claude or Codex, see docs/opencode.md"
                )
    _shape(launch, repository.get("default", ""))
    launch.git_prompts = not launch.directory and (
        repository.get("commit") == "deny" or repository.get("shipping", "deny") != "allow"
    )
    launch.approval_required = launch.service_actions or launch.git_prompts


def declaration(launch: Launch) -> None:
    """The declared task source gates the fetch flags, so a dispatcher never guesses."""
    launch.delivery = call(query.main, [launch.plot], capture=True)
    launch.tasks = call(query.main, ["--tasks", launch.plot], capture=True)
    if not (launch.redispatch or launch.abandon or launch.name.startswith(launch.plot + "-")):
        raise die(f"session name must begin with '{launch.plot}-'")
    if not launch.directory and launch.delivery == "-":
        raise die(f"plot '{launch.plot}' has no repository section and takes no repository path")


def repository(launch: Launch) -> None:
    """Require the supplied repository root before fetching an issue or preparing a worktree."""
    if launch.directory:
        return
    home = os.environ.get("HOME", "")
    spelled = home + launch.repo_arg[1:] if launch.repo_arg.startswith("~") else launch.repo_arg
    if not os.path.isdir(spelled):
        raise die(f"target repository not found: {launch.repo_arg}")
    top = subprocess.run(
        ["git", "-C", spelled, "rev-parse", "--show-toplevel"], capture_output=True, text=True
    )
    if (
        top.returncode
        or not top.stdout.strip()
        or Path(top.stdout.strip()).resolve() != Path(spelled).resolve()
    ):
        raise die(f"not a non-bare git repository: {launch.repo_arg}")
    launch.repo = Path(top.stdout.strip())


def sources(launch: Launch) -> None:
    for flag, needed in (("--issue", "github"), ("--note", "vault")):
        if getattr(launch, flag[2:]) and launch.tasks != needed:
            raise die(
                f"target '{launch.plot}' is declared {launch.tasks}, {flag} needs {needed}, "
                "pipe the kickoff on stdin instead"
            )
        if flag == "--issue" and launch.issue and launch.repo is None:
            raise die(
                "--issue runs gh inside the target checkout and this launch has none, "
                "pipe the kickoff on stdin instead"
            )
    if launch.issue_id and not (launch.tasks == "github" and launch.repo):
        raise die("issue association requires a GitHub repository plot")


def rendered(launch: Launch) -> None:
    if (
        not ((DIST / "claude").is_dir() and (DIST / "codex").is_dir())
        or not (DIST / "manifest.tsv").is_file()
    ):
        raise die("dist/ missing or incomplete — run bin/slopmeister render first")
    for tool in ("claude", "codex"):
        if not (DIST / tool / "plots" / f"{launch.plot}.md").is_file():
            raise die(
                f"no rendered plot at dist/{tool}/plots/{launch.plot}.md, "
                f"author plots/{launch.plot}/ and run task materialize"
            )


def name_lookup(launch: Launch) -> int:
    """pgrep's status for the session name, boundary-anchored so wt1 never matches inside wt10."""
    pattern = f"remote-control={launch.name}($| )"
    return subprocess.run(["pgrep", "-f", pattern], capture_output=True).returncode


def staged_file(launch: Launch, supplied: str = "") -> None:
    """The slot allocation, a regular file never named like the worktree's own git file."""
    launch.wt_file = supplied or os.environ.get("PLOT_SESSION_WORKTREE_FILE", "")
    if not launch.wt_file:
        return
    path = Path(launch.wt_file)
    if not path.is_file() or path.is_symlink():
        raise die(f"PLOT_SESSION_WORKTREE_FILE is not a regular file: {launch.wt_file}")
    launch.wt_file_name = path.name
    if launch.wt_file_name[:4].lower() == ".git":
        raise die(
            f"PLOT_SESSION_WORKTREE_FILE may not be named {launch.wt_file_name}, "
            "that is the worktree's own git file"
        )


def require_slot(launch: Launch, argv: Sequence[str]) -> None:
    if launch.directory or launch.redispatch or launch.abandon:
        return
    if launch.wt_file_name == ".slot.env":
        return
    body = launch.kickoff
    if launch.tool == "codex":
        body = body.removeprefix(f"{launch.name}\n\n")
    mode = next(
        (line for line in body.replace("\r", "").split("\n")[:MODE_LINES] if line in MODES), ""
    )
    if mode != "Mode: spine":
        return
    if call(query.main, ["--slots", launch.plot], capture=True) == "none\t-\t-":
        return
    options = next((number for number, arg in enumerate(argv) if arg.startswith("--")), len(argv))
    tail = argv[options:]
    if launch.extra:
        tail = tail[: -(len(launch.extra) + 1)]
    retry = shlex.join(["task", "slot:up", "--", str(launch.repo), launch.plot, launch.name, *tail])
    instruction = (
        "\nPipe the same kickoff on stdin again." if not (launch.issue or launch.note) else ""
    )
    if launch.extra:
        instruction += "\nAppend the original native tool arguments after --."
    raise plain(
        f"plot-session: plot '{launch.plot}' requires a slot for Mode: spine. "
        "No worktree or worker was created.\n"
        f"Retry: {retry}{instruction}"
    )


def codex_clients() -> set[int]:
    found = subprocess.run(["pgrep", "-f", "codex --no-daemon"], capture_output=True, text=True)
    return {int(pid) for pid in found.stdout.split()}


def binaries(launch: Launch) -> None:
    """Only the selected tool's binary is required."""
    if launch.tool == "claude":
        launch.claude_bin = shutil.which("claude") or ""
        if not launch.claude_bin:
            raise die("claude not found on PATH" + REPORT)
        return
    if launch.tool == "opencode":
        try:
            launch.opencode_bin = native.binary()
            native.require_provider(os.environ)
        except native.Blocked as blocked:
            raise die(str(blocked)) from blocked
        return
    if not os.access(launch.codex_bin, os.X_OK):
        raise die(f"codex not found at {launch.codex_bin}" + REPORT)
    launch.codex_baseline = codex_clients()
