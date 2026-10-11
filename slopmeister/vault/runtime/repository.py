"""External bare-repository initialization and literal named-path commits."""

from collections.abc import Sequence
from datetime import date
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys

USAGE = 'usage: slopmeister-vault commit "one line message" -- <vault-relative path>...'


def vault_path(value: str | None = None) -> Path:
    """The installed runtime imports no checkout, so it repeats the per-machine default."""
    default = Path.home() / ".slopmeister/vault"
    return Path(value or os.environ.get("SLOPMEISTER_VAULT") or default).expanduser()


def git_path() -> Path:
    return Path(os.environ.get("VAULT_GIT_DIR", Path.home() / ".vault-git/obsidian.git"))


def committed(path: str, expected: Sequence[bytes]) -> bool:
    if path_problem(path):
        return False
    result = subprocess.run(
        ["git", f"--git-dir={git_path()}", "show", f"HEAD:{path}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0 and all(value in result.stdout for value in expected)


def _dataless(path: Path) -> bool:
    flag = getattr(stat, "SF_DATALESS", 0)
    return bool(flag and getattr(path.stat(), "st_flags", 0) & flag)


def note_bytes(path: str, vault: Path | None = None) -> tuple[Path, bytes]:
    """Read one contained regular note, never a placeholder whose bytes are not on this disk."""
    if path_problem(path):
        raise OSError("note path must be vault-relative without parent or control segments")
    root = (vault or vault_path()).resolve(strict=True)
    subject = root / path
    if subject.is_symlink():
        raise OSError("note path must not be a symlink")
    resolved = subject.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise OSError("note path resolves outside the vault") from error
    if not resolved.is_file():
        raise OSError("note path is not a regular file")
    if _dataless(resolved):
        raise OSError(
            "note is a dataless placeholder, the Drive mirror has not put its bytes on this "
            "disk, find ~/.slopmeister/vault/ -flags +dataless must print nothing"
        )
    return resolved, resolved.read_bytes()


def _git(
    git_dir: Path, vault: Path, *args: str, quiet: bool = False
) -> subprocess.CompletedProcess:
    command = ["git", f"--git-dir={git_dir}", f"--work-tree={vault}", *args]
    return subprocess.run(
        command,
        env={**os.environ, "GIT_LITERAL_PATHSPECS": "1"},
        stdout=subprocess.DEVNULL if quiet else None,
        check=False,
    )


def _create(git_dir: Path, bundle: Path | None) -> int:
    command = (
        ["git", "clone", "--bare", "-q", str(bundle), str(git_dir)]
        if bundle
        else [
            "git",
            "init",
            "--bare",
            "-q",
            "-b",
            "main",
            str(git_dir),
        ]
    )
    return subprocess.run(command, check=False).returncode


def _baseline(vault: Path, git_dir: Path, bundle: Path | None) -> int:
    if bundle:
        print(f"history restored from {bundle}")
    exclude = Path(__file__).with_name("exclude")
    (git_dir / "info/exclude").write_bytes(exclude.read_bytes())
    status = _git(git_dir, vault, "add", "-A", quiet=True).returncode
    if status:
        return status
    kind = "snapshot after rebuild" if bundle else "baseline"
    message = f"Vault {kind} {date.today():%F}"
    committed = _git(git_dir, vault, "commit", "-q", "-m", message, quiet=True)
    if committed.returncode and not bundle:
        return committed.returncode
    count = subprocess.run(
        ["git", f"--git-dir={git_dir}", "rev-list", "--count", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    print(f"ready, {count} commit(s), run task home:install for the installed commands")
    return 0


def _initialize(vault: Path, git_dir: Path, bundle: Path | None) -> int:
    git_dir.parent.mkdir(parents=True, exist_ok=True)
    status = _create(git_dir, bundle)
    return status or _baseline(vault, git_dir, bundle)


def init_cli(vault_value: str | None, bundle_value: str | None) -> int:
    vault, git_dir = vault_path(vault_value), git_path()
    if not (vault / "_system").is_dir():
        print(f"required directory not found: {vault / '_system'}", file=sys.stderr)
        return 1
    if (vault / ".git").exists():
        message = f"{vault}/.git exists, remove it, the vault must hold nothing git-shaped"
        print(message, file=sys.stderr)
        return 1
    if git_dir.is_dir():
        print(f"repository already exists at {git_dir}")
        return 0
    bundle = Path(bundle_value).expanduser() if bundle_value else None
    return _initialize(vault, git_dir, bundle)


def _split_commit(argv: Sequence[str]) -> tuple[list[str], list[str]] | None:
    if "--" not in argv:
        return None
    split = list(argv).index("--")
    return list(argv[:split]), list(argv[split + 1 :])


def path_problem(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        not value
        or path.is_absolute()
        or not path.parts
        or ".." in value.split("/")
        or re.search(r"[\x00-\x1f\x7f]", value) is not None
    )


def locked(command: Sequence[str], paths: Sequence[str], *, input_text: str | None = None) -> int:
    lock = Path(os.environ.get("VAULT_LOCK", Path.home() / ".vault-git/bin/vault-lock.py"))
    if not lock.is_file() or not os.access(lock, os.X_OK):
        print(f"no vault lock helper at {lock}, run task home:install", file=sys.stderr)
        return 1
    launcher = os.environ.get("SLOPMEISTER_VAULT_LAUNCHER")
    reentry = [launcher, *command] if launcher else [sys.argv[0], "vault", *command]
    command = [
        sys.executable,
        str(lock),
        "--git-dir",
        str(git_path()),
        "--kind",
        "manual",
        "--timeout",
        "0",
    ]
    for path in paths:
        command += ["--path", path]
    return subprocess.run(
        [*command, "--", *reentry], input=input_text, text=input_text is not None, check=False
    ).returncode


def _lock_command(argv: Sequence[str], paths: Sequence[str]) -> int:
    return locked(["commit", *argv], paths)


def _commit(wrapper: Path, words: list[str], paths: list[str]) -> int:
    vault = vault_path()
    env = {**os.environ, "GIT_LITERAL_PATHSPECS": "1"}
    named = ", ".join(paths)
    status = subprocess.run([str(wrapper), "add", "--", *paths], cwd=vault, env=env)
    if status.returncode:
        print(f"vault add failed; named paths remain dirty: {named}", file=sys.stderr)
        return 1
    unchanged = subprocess.run(
        [str(wrapper), "diff", "--cached", "--quiet", "--", *paths], cwd=vault, env=env
    )
    if unchanged.returncode == 0:
        print("nothing to commit under the named paths", file=sys.stderr)
        return 1
    committed = subprocess.run(
        [str(wrapper), "commit", "-q", "-m", " ".join(words), "--", *paths],
        cwd=vault,
        env=env,
    )
    if committed.returncode:
        print(f"vault commit failed; named paths remain dirty: {named}", file=sys.stderr)
        return 1
    return subprocess.run(
        [str(wrapper), "show", "--stat", "--format=%h %s", "HEAD"], cwd=vault, env=env
    ).returncode


def commit_cli(argv: Sequence[str]) -> int:
    parts = _split_commit(argv)
    problem = "explicit paths are required" if parts is None or not parts[1] else None
    if parts is not None and not parts[0]:
        problem = "a message is required"
    elif parts is not None and any(path_problem(path) for path in parts[1]):
        problem = "paths must be vault-relative without root, parent or control segments"
    elif parts is not None and any((vault_path() / path).is_dir() for path in parts[1]):
        # This command runs unsandboxed and unprompted in every session, so a directory would
        # let one call commit notes another session is still writing.
        problem = "name each note, never a directory"
    if problem:
        print(f"refused: {problem}, {USAGE}", file=sys.stderr)
        return 2
    assert parts is not None
    words, paths = parts
    wrapper = Path(os.environ.get("VAULTGIT", Path.home() / ".vault-git/bin/vaultgit"))
    if not wrapper.is_file() or not os.access(wrapper, os.X_OK):
        print(f"no vaultgit wrapper at {wrapper}, run task home:install", file=sys.stderr)
        return 1
    if os.environ.get("SLOPMEISTER_VAULT_LOCKED") != "1":
        return _lock_command(argv, paths)
    return _commit(wrapper, words, paths)
