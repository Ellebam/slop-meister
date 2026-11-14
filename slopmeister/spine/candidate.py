"""Freeze and materialize one exact uncommitted repository candidate."""

from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from slopmeister.session import launch_identity, repositories

BASE_REF = "refs/slopmeister/base"
CANDIDATE_REF = "refs/slopmeister/candidate"
SHA = re.compile(r"[0-9a-f]{40}")
EMPTY_BASE_IDENTITY = {
    "GIT_AUTHOR_NAME": "Slopmeister",
    "GIT_AUTHOR_EMAIL": "candidate@example.invalid",
    "GIT_COMMITTER_NAME": "Slopmeister",
    "GIT_COMMITTER_EMAIL": "candidate@example.invalid",
    "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
}


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
    members: tuple[RepositoryCandidate, ...] = ()

    @property
    def identity(self) -> str:
        if not self.members:
            return self.tree
        values = [
            (str(item.workspace), item.common, item.base, item.tree)
            for item in (self, *self.members)
        ]
        return hashlib.sha256(json.dumps(values).encode()).hexdigest()


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
    if base:
        _bare(
            repository, "fetch", "-q", "--no-tags", "--force", str(workspace), f"{base}:{BASE_REF}"
        )
    else:
        # A private empty base keeps review copies usable without bootstrapping the target.
        tree = _bare(repository, "mktree")
        base = _bare(
            repository,
            "-c",
            "commit.gpgsign=false",
            "commit-tree",
            tree,
            "-m",
            "Empty repository baseline",
            env=EMPTY_BASE_IDENTITY,
        )
        _bare(repository, "update-ref", BASE_REF, base)
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


def _freeze_one(workspace: Path, task: str) -> RepositoryCandidate:
    workspace = workspace.resolve(strict=True)
    root = _root(workspace, task)
    base = _git(workspace, "rev-parse", "--revs-only", "HEAD^{commit}")
    repository = _object_store(root, workspace, base)
    base = _bare(repository, "rev-parse", "--verify", BASE_REF)
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
    _save(root / "candidate.json", value)
    return _load_one(workspace, task)


def freeze(workspace: Path, task: str) -> RepositoryCandidate:
    workspace = workspace.resolve(strict=True)
    roots = repositories.workspaces(workspace)
    primary, *companions = [_freeze_one(root, task) for root in roots]
    if companions:
        value = json.loads(primary.manifest.read_text())
        value["members"] = [str(root) for root in roots]
        _save(primary.manifest, value)
    return load(workspace, task)


def _save(path: Path, value: dict) -> None:
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".part")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _load_one(workspace: Path, task: str) -> RepositoryCandidate:
    try:
        workspace = workspace.resolve(strict=True)
        root = _root(workspace, task)
        repository, manifest = root / "repository.git", root / "candidate.json"
        value = launch_identity.private_json(manifest, "repository candidate manifest")
        required = {"version", "task", "common", "base", "tree", "scope"}
        if set(value) - {"members"} != required or value["version"] != 1 or value["task"] != task:
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
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise ValueError(f"repository member {workspace}: {error}") from error


def load(workspace: Path, task: str) -> RepositoryCandidate:
    primary = _load_one(workspace, task)
    roots = repositories.workspaces(primary.workspace)
    value = launch_identity.private_json(primary.manifest, "repository candidate manifest")
    recorded = value.get("members", [str(primary.workspace)])
    if recorded != [str(root) for root in roots]:
        raise ValueError(
            f"repository membership changed since freeze: frozen {recorded}, "
            f"current {[str(root) for root in roots]}"
        )
    return replace(primary, members=tuple(_load_one(root, task) for root in roots[1:]))


def _materialize_one(frozen: RepositoryCandidate, destination: Path) -> None:
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


def materialize(frozen: RepositoryCandidate, destination: Path) -> Path:
    if load(frozen.workspace, frozen.task).identity != frozen.identity:
        raise ValueError("repository candidate changed")
    _materialize_one(frozen, destination)
    for member in frozen.members:
        copied = destination / repositories.DIRECTORY / member.workspace.name
        copied.parent.mkdir(exist_ok=True)
        _materialize_one(member, copied)
    if frozen.members:
        with (destination / ".git/info/exclude").open("a") as stream:
            stream.write(f"\n/{repositories.DIRECTORY}/\n")
    return destination


def reading_guide(frozen: RepositoryCandidate) -> str:
    """How a reviewer, who cannot see the materialized layout, finds the whole change."""
    text = (
        f"\n\nThis checkout holds the frozen candidate as uncommitted changes over base commit "
        f"{frozen.base}, HEAD and the index are the base. Read the whole change with "
        "`git status --untracked-files=all` and `git diff HEAD`, and read every untracked file, "
        "each is new in the candidate."
    )
    if frozen.members:
        text += "\nReview and test every repository together, including:\n"
        text += "\n".join(
            f"- {'.' if item is frozen else repositories.DIRECTORY + '/' + item.workspace.name}: "
            f"review `git diff {repositories.read(item.workspace)['baseline']}` "
            f"and untracked files; captured base {item.base}, tree {item.tree}"
            for item in (frozen, *frozen.members)
        )
    return text


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


def verify_commit(
    frozen: RepositoryCandidate, commit: str, *, workspace: Path | None = None
) -> str:
    selected = workspace or frozen.workspace
    members = (frozen, *frozen.members)
    if selected not in {member.workspace for member in members}:
        raise ValueError(f"repository is not a member of the frozen candidate: {selected}")
    selected_commit = ""
    for member in members:
        try:
            revision = commit if member.workspace == selected else "HEAD"
            resolved = _git(
                member.workspace,
                "rev-parse",
                "--verify",
                "--end-of-options",
                f"{revision}^{{commit}}",
            )
            tree = _git(member.workspace, "rev-parse", "--verify", f"{resolved}^{{tree}}")
            if tree != member.tree:
                raise ValueError("commit does not match frozen candidate")
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise ValueError(f"repository member {member.workspace}: {error}") from error
        if member.workspace == selected:
            selected_commit = resolved
    return selected_commit
