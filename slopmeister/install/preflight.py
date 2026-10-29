"""Validate repository and directory destinations before installation."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess

from slopmeister.paths import codex_home
from slopmeister.session import git_environment

ROOTS = (
    "AGENTS.md",
    "CLAUDE.md",
    "AGENTS.override.md",
    "CLAUDE.local.md",
    ".claude",
    ".codex",
    ".agents",
    ".mcp.json",
)
NATIVE_DIRS = {".claude", ".codex", ".agents"}
DIRECTORIES = (".claude/skills", ".claude/agents", ".claude/commands", ".agents/skills")


@dataclass(frozen=True)
class GitOptions:
    data: bytes | None = None
    optional: bool = False


def refuse(message: str) -> None:
    raise ValueError(message)


def git(repo: Path, args: tuple[str, ...], options: GitOptions | None = None) -> bytes:
    options = options or GitOptions()
    command = ["git", "--no-optional-locks", "-C", str(repo), *args]
    result = subprocess.run(
        command, input=options.data, capture_output=True, env=git_environment.child()
    )
    if result.returncode and not options.optional:
        refuse(
            "Git refused configuration preparation or validation: "
            + result.stderr.decode(errors="replace").strip()
        )
    return result.stdout if result.returncode == 0 else b""


def setting(repo: Path, key: str) -> str:
    return git(repo, ("config", "--get", key), GitOptions(optional=True)).decode().strip()


def safe_path(path: Path, *, link: bool = False) -> None:
    for ancestor in reversed((path, *path.parents)):
        if ancestor.is_symlink() and not (link and ancestor == path):
            refuse("symlinked configuration path: " + str(ancestor))


def protected(path: str, roots: list[str]) -> bool:
    return any(path == root or path.startswith(root + "/") for root in roots)


def configuration_roots(entries: list[bytes]) -> list[str]:
    roots = set(ROOTS)
    for entry in filter(None, entries):
        _, raw = entry.split(b"\t", 1)
        relative = os.fsdecode(raw)
        parts = relative.split("/")
        _add_native_root(roots, parts, relative)
        if parts[0].casefold() in {p.casefold() for p in ROOTS} and parts[0] not in ROOTS:
            refuse("case-folded configuration path collision: " + relative)
    return sorted(
        p for p in roots if not any(p.startswith(other + "/") for other in roots if other != p)
    )


def _add_native_root(roots: set[str], parts: list[str], relative: str) -> None:
    for index, part in enumerate(parts):
        if part.casefold() not in NATIVE_DIRS | {".mcp.json"}:
            continue
        if part != part.casefold():
            refuse("case-folded configuration path collision: " + relative)
        roots.add("/".join(parts[: index + 1]))
        return


def repository_paths(repo: Path) -> tuple[Path, Path]:
    raw = git(repo, ("rev-parse", "--path-format=absolute", "--git-common-dir"))
    common = Path(os.fsdecode(raw).strip())
    safe_path(common)
    for relative in ("config", "info", "info/exclude"):
        safe_path(common / relative)
    _reject_shared_configuration(repo, common)
    if (
        git(
            repo,
            ("config", "--type=bool", "--get", "core.sparseCheckout"),
            GitOptions(optional=True),
        ).strip()
        == b"true"
    ):
        refuse("sparse checkout is incompatible with fixed configuration")
    top = Path(os.fsdecode(git(repo, ("rev-parse", "--show-toplevel"))).strip())
    if top != repo:
        refuse("configuration destination must be a repository root")
    gitdir = Path(os.fsdecode(git(repo, ("rev-parse", "--absolute-git-dir"))).strip())
    safe_path(gitdir)
    safe_path(gitdir / "config.worktree")
    return common, gitdir


def _reject_shared_configuration(repo: Path, common: Path) -> None:
    for key in ("core.worktree", "core.bare"):
        kind = ("--type=bool",) if key == "core.bare" else ()
        args = ("config", "--file", str(common / "config"), "--includes", *kind, "--get", key)
        value = git(repo, args, GitOptions(optional=True)).strip()
        if value and (key == "core.worktree" or value.lower() == b"true"):
            refuse("incompatible shared " + key + "; no preparation writes occurred")


def directory_parent(repo: Path) -> None:
    probe = repo.parent
    while not probe.exists():
        probe = probe.parent
    if git(probe, ("rev-parse", "--show-toplevel"), GitOptions(optional=True)):
        refuse("session directory must be outside every Git repository")
    globals_ = _global_configuration_roots()
    for parent in (probe, *probe.parents):
        _reject_ancestor_configuration(parent, globals_)


def _global_configuration_roots() -> set[Path]:
    home = Path.home()
    return {
        Path(os.environ.get("CLAUDE_CONFIG_DIR", str(home / ".claude"))).resolve(),
        codex_home().resolve(),
        (home / ".agents").resolve(),
    }


def _reject_ancestor_configuration(parent: Path, globals_: set[Path]) -> None:
    for name in ROOTS:
        candidate = parent / name
        if candidate.resolve() in globals_:
            continue
        try:
            if (
                name in NATIVE_DIRS
                and not candidate.is_symlink()
                and candidate.is_dir()
                and not any(candidate.iterdir())
            ):
                continue
        except OSError:
            pass
        if candidate.exists() or candidate.is_symlink():
            refuse(
                "ancestor project configuration at "
                + str(candidate)
                + "; choose a clean session directory"
            )


def reject_git_context() -> None:
    if name := git_environment.redirect():
        refuse("configuration preparation refuses Git context override " + name)


def preflight(repo: Path) -> tuple[Path, Path]:
    common, gitdir = repository_paths(repo)
    safe_path(repo / ".worktrees")
    print("Slopmeister configuration preflight passed")
    return common, gitdir
