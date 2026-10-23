"""External bare-repository initialization and literal named-path commits."""

from collections.abc import Sequence
import os
from pathlib import Path, PurePosixPath
import re
import signal
import stat
import subprocess
import sys

from .environment import commit_environment, git_path, vault_path
from .initialization import init_cli as init_cli

USAGE = 'usage: slopmeister-vault commit "one line message" -- <vault-relative path>...'


def committed(path: str, expected: Sequence[bytes]) -> bool:
    if path_problem(path):
        return False
    result = subprocess.run(
        ["git", f"--git-dir={git_path()}", "show", f"HEAD:{path}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        env=commit_environment(),
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


def _lock_command(
    command: Sequence[str], paths: Sequence[str], wait_seconds: float = 0
) -> tuple[list[str], dict[str, str]]:
    env = commit_environment()
    lock = Path(env["VAULT_LOCK"])
    if not lock.is_file() or not os.access(lock, os.X_OK):
        print(f"no vault lock helper at {lock}, run task home:install", file=sys.stderr)
        raise ValueError("vault lock helper is unavailable")
    launcher = env.get("SLOPMEISTER_VAULT_LAUNCHER")
    reentry = [launcher, *command] if launcher else [sys.argv[0], "vault", *command]
    command = [
        sys.executable,
        "-I",
        str(lock),
        "--git-dir",
        env["VAULT_GIT_DIR"],
        "--kind",
        "manual",
        "--timeout",
        str(wait_seconds),
    ]
    for path in paths:
        command += ["--path", path]
    return [*command, "--", *reentry], env


def locked(command: Sequence[str], paths: Sequence[str], *, input_text: str | None = None) -> int:
    try:
        argv, env = _lock_command(command, paths)
    except ValueError:
        return 1
    return _wait_holder(argv, env, input_text)


def _wait_holder(command: list[str], env: dict[str, str], text: str | None = None) -> int:
    process = subprocess.Popen(
        command, env=env, stdin=subprocess.PIPE if text is not None else None, text=text is not None
    )
    previous = {
        sig: signal.signal(sig, lambda sig, _: process.send_signal(sig))
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    }
    try:
        process.communicate(text)
        return process.returncode
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _commit(wrapper: Path, words: list[str], paths: list[str]) -> int:
    env = commit_environment()
    vault = Path(env["SLOPMEISTER_VAULT"])
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


def commit_cli(argv: Sequence[str], *, wait_seconds: float = 0) -> int:
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
    wrapper = Path(commit_environment()["VAULTGIT"])
    if not wrapper.is_file() or not os.access(wrapper, os.X_OK):
        print(f"no vaultgit wrapper at {wrapper}, run task home:install", file=sys.stderr)
        return 1
    if os.environ.get("SLOPMEISTER_VAULT_LOCKED") != "1":
        try:
            command, env = _lock_command(["commit", *argv], paths, wait_seconds)
        except ValueError:
            status = 1
        else:
            status = _wait_holder(command, env)
        return status
    return _commit(wrapper, words, paths)
