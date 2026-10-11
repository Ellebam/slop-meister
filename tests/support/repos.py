"""Disposable Git repositories with a fixed identity, so tests never touch the operator's config."""

from pathlib import Path
import subprocess

GIT_ENV = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def git(repo: Path, *args: str) -> str:
    import os

    env = {**os.environ, **GIT_ENV}
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, env=env, check=True
    )
    return result.stdout


def scratch_repo(path: Path, *, branch: str = "main") -> Path:
    """An initialised repository with one commit on `branch`."""
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", branch)
    (path / "README.md").write_text("scratch\n")
    git(path, "add", "README.md")
    git(path, "commit", "-q", "-m", "Initial")
    return path
