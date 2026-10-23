"""Run repository setup and retain ownership of only its unchanged generated files."""

import json
import os
from pathlib import Path
import stat
import subprocess

from slopmeister.check import jobs
from slopmeister.errors import SlopmeisterError
from slopmeister.launch.model import Launch
from slopmeister.removal import IGNORED_ARGS, _digest, _files, check_ignored
from slopmeister.slots import allocation

RECORD = "setup.json"
LOG = "setup.log"
TIMEOUT = 900


def _contained(root: Path, name: str, *, allow_metadata: bool = False) -> Path:
    relative = Path(name)
    forbidden = {"", ".", ".."} if allow_metadata else {"", ".", "..", ".git", ".slot.env"}
    if relative.is_absolute() or any(part in forbidden for part in name.split("/")):
        raise SlopmeisterError("unsafe setup output path")
    path = root / relative
    if any(
        (root.joinpath(*relative.parts[:n])).is_symlink() for n in range(1, len(relative.parts) + 1)
    ):
        raise SlopmeisterError(f"symlinked setup output: {name}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise SlopmeisterError(f"setup output escapes checkout: {name}")
    return path


def _destinations(root: Path, outputs: list[str]) -> None:
    for name in outputs:
        path = _contained(root, name)
        tracked = allocation.run(
            ["git", "-C", str(root), "ls-files", "--", name], capture=True
        ).stdout.strip()
        if tracked or os.path.lexists(path):
            raise SlopmeisterError(f"setup output already exists or is tracked: {name}")


def _snapshot(root: Path, outputs: list[str]) -> dict[str, str]:
    result = {}
    for name in outputs:
        if not _contained(root, name).exists():
            raise SlopmeisterError(f"missing setup output: {name}")
    for path, info, _marker in _files(root, ["? " + name for name in outputs]):
        name = path.relative_to(root).as_posix()
        _contained(root, name)
        if not stat.S_ISREG(info.st_mode):
            raise SlopmeisterError(f"setup output is not a regular file: {name}")
        result[name] = _digest(path)
    return result


def _execute(claim: allocation.Claim, command: list[str]) -> None:
    environment = dict(os.environ)
    environment.update(line.split("=", 1) for line in allocation.content(claim).splitlines())
    descriptor = os.open(claim.data / LOG, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as log:
        process = subprocess.Popen(
            command,
            cwd=claim.live.worktree,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            jobs.wait_unreaped(process, TIMEOUT)
        except subprocess.TimeoutExpired as error:
            raise SlopmeisterError(
                f"setup exceeded {TIMEOUT} seconds; see {claim.data / LOG}"
            ) from error
        finally:
            jobs.stop_group(process, anchored=True)
    if process.returncode:
        raise SlopmeisterError(f"setup exited {process.returncode}; see {claim.data / LOG}")


def run(claim: allocation.Claim, slots: dict) -> None:
    """Callable after stack readiness in either a worker or a tester's prepared checkout."""
    if not (command := slots.get("setup")):
        return
    outputs = slots.get("setup_files", [])
    _destinations(claim.live.worktree, outputs)
    _execute(claim, command)
    record = _snapshot(claim.live.worktree, outputs)
    descriptor = os.open(claim.data / RECORD, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(record, stream, sort_keys=True)


def remaining(root: Path, names: list[str], data: Path) -> list[str]:
    """Keep the ordinary removal guard for every file not owned by this setup run."""
    record = data / RECORD
    if not os.path.lexists(record):
        return names
    if record.is_symlink():
        raise SlopmeisterError("symlinked setup ownership record")
    known = json.loads(record.read_text())
    if not isinstance(known, dict) or not all(
        isinstance(name, str) and isinstance(digest, str) for name, digest in known.items()
    ):
        raise SlopmeisterError("unreadable setup ownership record")
    for name in known:
        _contained(root, name)
    kept = []
    for path, info, marker in _files(root, names):
        saved = known.get(path.relative_to(root).as_posix())
        try:
            if saved and stat.S_ISREG(info.st_mode) and saved == _digest(path):
                continue
        except OSError:
            pass
        kept.append(marker + path.relative_to(root).as_posix())
    return kept


def _saved_tmp(root: Path, relative: str, proof: Path) -> bool:
    try:
        source = _contained(root, relative, allow_metadata=True)
        copy = _contained(proof, Path(relative).relative_to("tmp").as_posix(), allow_metadata=True)
        if proof.resolve().is_relative_to(root.resolve()) or any(
            path.is_symlink() for path in (proof, *proof.parents)
        ):
            return False
        info = copy.lstat()
        return (
            stat.S_ISREG(info.st_mode)
            and bool(info.st_mode & 0o444)
            and _digest(source) == _digest(copy)
        )
    except OSError, SlopmeisterError:
        return False


def _release_remaining(root: Path, names: list[str], owned: allocation.Live) -> list[str]:
    proof = Launch(owned.target, owned.name, str(root)).state_dir / f"{owned.name}-proof"
    kept = []
    for path, info, marker in _files(root, names):
        relative = path.relative_to(root).as_posix()
        removable = False
        if marker == "? " and stat.S_ISREG(info.st_mode) and info.st_mode & 0o444:
            try:
                _contained(root, relative, allow_metadata=relative.startswith("tmp/"))
                removable = relative.startswith("tmp/") and _saved_tmp(root, relative, proof)
            except SlopmeisterError:
                pass
        if not removable:
            kept.append(marker + relative)
    return kept


def check_ignored_output(worktree: Path, owned: allocation.Live) -> None:
    command = ["git", "-C", str(worktree)]
    entries = allocation.run([*command, *IGNORED_ARGS], capture=True).stdout.split("\0")
    names = [entry for entry in entries if entry.startswith(("? ", "S ", "s ", "h "))]
    gitdir = allocation.run([*command, "rev-parse", "--absolute-git-dir"], capture=True).stdout
    record = allocation.state_path() / f"{owned.target}-slot{owned.slot}" / allocation.ALLOCATION
    if (worktree / allocation.ALLOCATION).read_bytes() == record.read_bytes():
        names = [name for name in names if name[2:] != allocation.ALLOCATION]
    check_ignored(
        worktree,
        _release_remaining(worktree, remaining(worktree, names, record.parent), owned),
        Path(gitdir.strip()) / "slopmeister-config",
    )
