"""Freeze and materialize one exact uncommitted repository candidate."""

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import tempfile

from slopmeister.session import launch_identity
from slopmeister.spine.tester.runs import save

BASE_REF = "refs/slopmeister/base"
CANDIDATE_REF = "refs/slopmeister/candidate"
SHA = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True)
class RepositoryCandidate:
    workspace: Path
    repository: Path
    manifest: Path
    task: str
    common: str
    base: str
    tree: str
    scope: tuple[str, ...]


def _git(cwd: Path, *args: str, env: dict[str, str] | None = None, raw: bool = False):
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=30,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", **(env or {})},
    )
    if result.returncode:
        detail = os.fsdecode(result.stderr or result.stdout).strip()
        raise ValueError(f"git {args[0]} failed: {detail}")
    return result.stdout if raw else os.fsdecode(result.stdout).strip()


def _bare(repository: Path, *args: str, worktree: Path | None = None, env=None):
    command = ["--git-dir", str(repository)]
    if worktree is not None:
        command.extend(("--work-tree", str(worktree)))
    return _git(worktree or repository.parent, *command, *args, env=env)


def _common(workspace: Path) -> Path:
    return Path(
        _git(workspace, "rev-parse", "--path-format=absolute", "--git-common-dir")
    ).resolve()


def _root(workspace: Path, task: str) -> Path:
    if not launch_identity.TASK.fullmatch(task):
        raise ValueError("invalid launcher task identity")
    root = _common(workspace) / "slopmeister-config/candidates" / task
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or root.stat().st_uid != os.getuid():
        raise ValueError("unsafe repository candidate directory")
    root.chmod(0o700)
    return root


def _scope(repository: Path, base: str, tree: str) -> tuple[str, ...]:
    value = _git(
        repository.parent,
        "--git-dir",
        str(repository),
        "diff",
        "--name-only",
        "--no-renames",
        "-z",
        f"{base}^{{tree}}",
        tree,
        "--",
        raw=True,
    )
    return tuple(os.fsdecode(path) for path in value.split(b"\0") if path)


def _skip_worktree(workspace: Path) -> tuple[str, ...]:
    value = _git(workspace, "ls-files", "-v", "-z", raw=True)
    return tuple(os.fsdecode(row[2:]) for row in value.split(b"\0") if row.startswith(b"S "))


def _object_store(root: Path, workspace: Path, base: str) -> Path:
    repository = root / "repository.git"
    if not repository.exists():
        _git(root, "init", "--bare", "-q", str(repository))
        repository.chmod(0o700)
    if repository.is_symlink() or not repository.is_dir():
        raise ValueError("unsafe repository candidate object store")
    _bare(repository, "fetch", "-q", "--no-tags", "--force", str(workspace), f"{base}:{BASE_REF}")
    return repository


def _write_tree(repository: Path, workspace: Path, base: str) -> str:
    with tempfile.TemporaryDirectory(dir=repository.parent, prefix="freeze-") as temporary:
        environment = {
            "GIT_INDEX_FILE": str(Path(temporary) / "index"),
            "GIT_OBJECT_DIRECTORY": str(repository / "objects"),
        }
        _git(workspace, "read-tree", base, env=environment)
        hidden = _skip_worktree(workspace)
        if hidden:
            _git(workspace, "update-index", "--skip-worktree", "--", *hidden, env=environment)
        _git(workspace, "add", "-A", "--", env=environment)
        return _git(workspace, "write-tree", env=environment)


def freeze(workspace: Path, task: str) -> RepositoryCandidate:
    workspace = workspace.resolve(strict=True)
    root = _root(workspace, task)
    base = _git(workspace, "rev-parse", "--verify", "HEAD^{commit}")
    repository = _object_store(root, workspace, base)
    tree = _write_tree(repository, workspace, base)
    _bare(repository, "update-ref", CANDIDATE_REF, tree)
    scope = _scope(repository, base, tree)
    value = {
        "version": 1,
        "task": task,
        "common": str(_common(workspace)),
        "base": base,
        "tree": tree,
        "scope": list(scope),
    }
    save(root / "candidate.json", value)
    return load(workspace, task)


def load(workspace: Path, task: str) -> RepositoryCandidate:
    workspace = workspace.resolve(strict=True)
    root = _root(workspace, task)
    repository, manifest = root / "repository.git", root / "candidate.json"
    value = launch_identity.private_json(manifest, "repository candidate manifest")
    required = {"version", "task", "common", "base", "tree", "scope"}
    if set(value) != required or value["version"] != 1 or value["task"] != task:
        raise ValueError("invalid repository candidate manifest")
    base, tree, scope = value["base"], value["tree"], value["scope"]
    if (
        value["common"] != str(_common(workspace))
        or not isinstance(base, str)
        or not SHA.fullmatch(base)
        or not isinstance(tree, str)
        or not SHA.fullmatch(tree)
        or not isinstance(scope, list)
        or not all(isinstance(path, str) for path in scope)
    ):
        raise ValueError("invalid repository candidate identity")
    if _bare(repository, "rev-parse", "--verify", f"{BASE_REF}^{{commit}}") != base:
        raise ValueError("repository candidate base changed")
    if _bare(repository, "rev-parse", "--verify", f"{CANDIDATE_REF}^{{tree}}") != tree:
        raise ValueError("repository candidate tree changed")
    if tuple(scope) != _scope(repository, base, tree):
        raise ValueError("repository candidate scope changed")
    return RepositoryCandidate(
        workspace, repository, manifest, task, value["common"], base, tree, tuple(scope)
    )


def load_for_session(workspace: Path, task: str, tool: str) -> RepositoryCandidate:
    identity = launch_identity.read(workspace, tool)
    if task != identity["task"]:
        raise ValueError("tester task differs from launcher task")
    return load(workspace, task)


def materialize(frozen: RepositoryCandidate, destination: Path) -> Path:
    load(frozen.workspace, frozen.task)
    _git(destination.parent, "init", "-q", str(destination))
    _git(
        destination,
        "fetch",
        "-q",
        "--no-tags",
        str(frozen.repository),
        f"{BASE_REF}:{BASE_REF}",
        f"{CANDIDATE_REF}:{CANDIDATE_REF}",
    )
    _git(destination, "checkout", "-q", "--detach", BASE_REF)
    _git(destination, "read-tree", "--reset", "-u", CANDIDATE_REF)
    _git(destination, "read-tree", "--reset", f"{BASE_REF}^{{tree}}")
    if worktree_tree(destination) != frozen.tree:
        raise ValueError("materialized repository candidate changed")
    return destination


def reading_guide(frozen: RepositoryCandidate) -> str:
    """How a reviewer, who cannot see the materialized layout, finds the whole change."""
    return (
        f"\n\nThis checkout holds the frozen candidate as uncommitted changes over base commit "
        f"{frozen.base}, HEAD and the index are the base. Read the whole change with "
        "`git status --untracked-files=all` and `git diff HEAD`, and read every untracked file, "
        "each is new in the candidate."
    )


@contextmanager
def isolated(frozen: RepositoryCandidate):
    with tempfile.TemporaryDirectory(prefix="slopmeister-candidate-") as temporary:
        yield materialize(frozen, Path(temporary) / "checkout")


def _staged_tree(workspace: Path, base: str, update: str) -> str:
    workspace = workspace.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="slopmeister-candidate-index-") as temporary:
        environment = {"GIT_INDEX_FILE": str(Path(temporary) / "index")}
        _git(workspace, "read-tree", base, env=environment)
        _git(workspace, "add", update, "--", env=environment)
        return _git(workspace, "write-tree", env=environment)


def worktree_tree(workspace: Path) -> str:
    return _staged_tree(workspace, "HEAD", "-A")


def head_tree(workspace: Path) -> str:
    return _git(workspace, "rev-parse", "--verify", "HEAD^{tree}")


def unchanged(workspace: Path, tree: str) -> bool:
    """Whether every path of `tree` is intact in the work tree; other paths are not looked at."""
    return _staged_tree(workspace, tree, "-u") == tree


def verify_commit(frozen: RepositoryCandidate, commit: str) -> str:
    resolved = _git(frozen.workspace, "rev-parse", "--verify", f"{commit}^{{commit}}")
    tree = _git(frozen.workspace, "rev-parse", "--verify", f"{resolved}^{{tree}}")
    if tree != frozen.tree:
        raise ValueError("commit does not match frozen candidate")
    return resolved
