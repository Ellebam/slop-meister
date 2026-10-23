"""Create or restore an external vault repository without changing the vault layout."""

from datetime import date
from pathlib import Path
import subprocess
import sys

from .environment import commit_environment, git_path, vault_path


def _git(
    git_dir: Path, vault: Path, *args: str, quiet: bool = False
) -> subprocess.CompletedProcess:
    command = ["git", f"--git-dir={git_dir}", f"--work-tree={vault}", *args]
    return subprocess.run(
        command,
        env=commit_environment(),
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
    return subprocess.run(command, env=commit_environment(), check=False).returncode


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
        env=commit_environment(),
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
