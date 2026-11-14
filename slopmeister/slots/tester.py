"""Lend a worker allocation to a clean diff checkout without transferring stack ownership."""

from dataclasses import replace
import fcntl
import json
import os
from pathlib import Path

from slopmeister.errors import SlopmeisterError
from slopmeister.removal import remove_tree
from slopmeister.slots import allocation, setup
from slopmeister.threads import occupants

RECORD = allocation.TESTER_RECORD


def _record(data: Path) -> dict:
    path = data / RECORD
    if path.is_symlink() or data.is_symlink():
        raise SlopmeisterError(f"check lease is a symlink: {data}")
    try:
        record = json.loads(path.read_text())
        allocation.validate_name(record["target"], "target")
        allocation.validate_name(record["name"], "session")
        if type(record["admitted"]) is not bool:
            raise ValueError("invalid check admission state")
        if type(record["slot"]) is not int or not 1 <= record["slot"] <= 99:
            raise ValueError("invalid slot")
        if data != allocation.state_path() / f"{record['target']}-slot{record['slot']}":
            raise ValueError("lease path disagrees with slot")
        if not all(Path(record[key]).is_absolute() for key in ("repository", "run", "worker")):
            raise ValueError("invalid lease paths")
        if Path(record["worker"]) != Path(record["repository"]) / ".worktrees" / record["name"]:
            raise ValueError("worker path disagrees with allocation")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SlopmeisterError(
            f"unreadable or legacy tester ownership at {path}; preserve it for repair"
        ) from error
    return record


def _worker(run: dict, target: str) -> tuple[allocation.Claim, dict]:
    allocation.validate_name(target, "target")
    worker = Path(run["cwd"]).resolve(strict=True)
    path = worker / allocation.ALLOCATION
    if path.is_symlink() or not path.is_file():
        raise SlopmeisterError("the diff check requires the worker's regular .slot.env")
    item = allocation.read(path)
    repository = allocation.main_root(str(worker))
    slots = allocation.definition(target)
    if item.target != target or worker != repository / ".worktrees" / item.name:
        raise SlopmeisterError("worker allocation does not belong to the requested plot")
    if allocation.is_none(slots) or not 1 <= item.slot <= allocation.maximum(slots):
        raise SlopmeisterError("worker allocation is outside the declared slot range")
    if not slots.get("setup"):
        raise SlopmeisterError("slot checks require a declared setup lifecycle route")
    data = allocation.state_path() / f"{target}-slot{item.slot}"
    relative = allocation.compose_relative(slots)
    compose = allocation.resolve_compose(worker, relative) if relative else None
    claim = allocation.Claim(item, data, compose, allocation.expand(slots, item.slot))
    expected = allocation.content(claim)
    state = data / allocation.ALLOCATION
    if (
        data.is_symlink()
        or state.is_symlink()
        or (path.read_text() != expected or state.read_text() != expected)
    ):
        raise SlopmeisterError("worker allocation changed or disagrees with owned state")
    return claim, slots


def _initialize(root: Path, claim: allocation.Claim) -> int:
    path = claim.data / RECORD
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        raise SlopmeisterError(f"a diff check holds or retained this leased slot: {path}") from None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        record = dict(
            run=str(root),
            repository=str(allocation.main_root(str(claim.live.worktree))),
            worker=str(claim.live.worktree),
            environment=allocation.content(claim),
            target=claim.live.target,
            name=claim.live.name,
            slot=claim.live.slot,
            admitted=False,
        )
        with os.fdopen(os.dup(fd), "w") as stream:
            json.dump(record, stream)
            stream.flush()
            os.fsync(stream.fileno())
        return fd
    except BaseException:
        os.close(fd)
        raise


def _deliver(checkout: Path, environment: str) -> None:
    path = checkout / allocation.ALLOCATION
    tracked = allocation.run(
        ["git", "-C", str(checkout), "ls-files", "--", allocation.ALLOCATION], capture=True
    ).stdout.strip()
    if tracked or os.path.lexists(path):
        raise SlopmeisterError(f"tester allocation destination already exists: {path}")
    with path.open("x") as stream:
        stream.write(environment)
    with (checkout / ".git/info/exclude").open("a") as stream:
        stream.write("\n/.slot.env\n")


def prepare(root: Path, run: dict, target: str) -> None:
    """Hold the worker slot before stop/reset. Failed preparation keeps a recovery lease."""
    claim, slots = _worker(run, target)
    fd = _initialize(root, claim)
    run["slot"] = {"state": str(claim.data), "fd": fd}
    try:
        _deliver(Path(run["checkout"]), allocation.content(claim))
        setup.phase(claim, slots, "stop", root)
        check_claim = replace(claim, live=replace(claim.live, worktree=Path(run["checkout"])))
        setup.phase(check_claim, slots, "reset", root)
        with os.fdopen(os.dup(fd), "r+") as stream:
            stream.seek(0)
            record = json.load(stream)
            record["admitted"] = True
            stream.seek(0)
            json.dump(record, stream)
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException as error:
        run["slot_cleanup_error"] = str(error)
        raise


def _verify(root: Path, slot: dict) -> tuple[dict, allocation.Claim, dict]:
    if root.is_symlink() or root.resolve() != root:
        raise SlopmeisterError("check run path changed; lease retained")
    data = Path(slot["state"])
    record = _record(data)
    held, current = os.fstat(slot["fd"]), (data / RECORD).stat()
    if (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino) or record["run"] != str(root):
        raise SlopmeisterError("check lease ownership changed; allocation retained")
    claim, slots = _worker({"cwd": record["worker"]}, record["target"])
    if allocation.content(claim) != record["environment"]:
        raise SlopmeisterError("check lease allocation changed")
    checkout = root / "checkout"
    path = checkout / allocation.ALLOCATION
    if (
        checkout.is_symlink()
        or path.is_symlink()
        or (path.exists() and path.read_text() != record["environment"])
        or (record.get("admitted") is True and checkout.exists() and not path.is_file())
    ):
        raise SlopmeisterError("tester checkout allocation changed")
    return record, claim, slots


def _restore(root: Path, slot: dict, ready: bool = True) -> None:
    _, claim, slots = _verify(root, slot)
    checkout = root / "checkout"
    if any(process.inside for process in occupants.census(str(checkout))):
        raise SlopmeisterError(f"a checker still occupies {checkout}; lease retained")
    if (checkout / allocation.ALLOCATION).is_file():
        checked = replace(claim, live=replace(claim.live, worktree=checkout))
        setup.phase(checked, slots, "stop", root)
    else:
        # An interrupted delivery can leave the original worker applications running.
        setup.phase(claim, slots, "stop", root)
    setup.phase(claim, slots, "reset", root)
    if ready:
        setup.phase(claim, slots, "ready", root)
    # Keep the lease if deletion fails, so the worker cannot race unfinished cleanup.
    if checkout.exists():
        remove_tree(checkout)
    _verify(root, slot)
    (claim.data / RECORD).unlink()


def cleanup(root: Path, run: dict, preparation: bool = False) -> str | None:
    """Restore the worker, then remove only this lease and its private checkout."""
    if "slot" not in run:
        return None
    slot = run.pop("slot")
    try:
        if run.get("process_stopped") is False:
            raise SlopmeisterError("checker stop unverified; slot lease retained")
        if error := run.get("slot_cleanup_error"):
            raise SlopmeisterError(f"preparation failed; slot lease retained: {error}")
        _restore(root, slot, run.get("ready", True))
    except (OSError, ValueError, KeyError, SlopmeisterError) as error:
        return str(error)
    finally:
        os.close(slot["fd"])
    return None


def find(target: str, name: str, wanted: str) -> Path | None:
    allocation.validate_name(target, "target")
    allocation.validate_name(name, "session")
    if not wanted.isdigit() or len(wanted) > 2 or not 1 <= int(wanted) <= 99:
        raise SlopmeisterError("check recovery requires a slot number from 1 to 99")
    data = allocation.state_path() / f"{target}-slot{wanted}"
    if not os.path.lexists(data / RECORD):
        return None
    if _record(data)["name"] != name:
        raise SlopmeisterError("check lease belongs to another worker")
    return data


def recover(data: Path, repository: Path, wanted: str) -> None:
    fd = os.open(data / RECORD, os.O_RDWR | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SlopmeisterError("a diff check still holds this allocation") from None
        record = _record(data)
        if repository != Path(record["repository"]) or wanted != str(record["slot"]):
            raise SlopmeisterError("check recovery requires its repository and exact --slot number")
        _restore(Path(record["run"]), {"state": str(data), "fd": fd})
        print(f"slot: {record['target']}-slot{record['slot']} check lease recovered; worker ready")
    finally:
        os.close(fd)
