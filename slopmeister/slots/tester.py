"""Lease the existing slot owner's ports to one external tester checkout."""

from contextlib import contextmanager
from dataclasses import replace
import fcntl
from functools import partial
import json
import os
from pathlib import Path
import re
import tempfile

from slopmeister.errors import SlopmeisterError
from slopmeister.slots import allocation, compose, up
from slopmeister.threads import occupants

RECORD = allocation.TESTER_RECORD


def _record(data: Path) -> dict:
    path = data / RECORD
    if path.is_symlink() or data.is_symlink():
        raise SlopmeisterError(f"tester allocation is a symlink: {data}")
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise SlopmeisterError(
            f"unreadable tester ownership at {path}. Preserve it for repair"
        ) from error
    allocation.validate_name(record["target"], "target")
    allocation.validate_name(record["name"], "session")
    if type(record["slot"]) is not int or not 1 <= record["slot"] <= 99:
        raise SlopmeisterError(f"tester allocation has an invalid slot: {data}")
    if data != allocation.state_path() / f"{record['target']}-slot{record['slot']}":
        raise SlopmeisterError(f"tester allocation path disagrees with its identity: {data}")
    if not all(Path(record[key]).is_absolute() for key in ("repository", "run")):
        raise SlopmeisterError(f"tester allocation has invalid checkout paths: {data}")
    return record


def _claim(root: Path, run: dict, target: str) -> allocation.Claim:
    allocation.validate_name(target, "target")
    if run.get("subject_manifest"):
        raise SlopmeisterError("tester slots require a repository checkout")
    slots = allocation.definition(target)
    if allocation.is_none(slots):
        raise SlopmeisterError(f"target '{target}' declares no slot resources")
    checkout = Path(run["checkout"])
    path = checkout / allocation.ALLOCATION
    tracked = allocation.run(
        ["git", "-C", str(checkout), "ls-files", "--", allocation.ALLOCATION], capture=True
    ).stdout.strip()
    if tracked or os.path.lexists(path):
        raise SlopmeisterError(f"tester allocation destination already exists: {path}")
    name = f"{target}-tester-{re.sub('[^a-z0-9-]', '-', root.name.lower())}"
    allocation.validate_name(name, "tester")
    repository = allocation.main_root(run["cwd"])
    context = {"run": str(root), "repository": str(repository)}
    prepare = partial(_initialize, context=context)
    request = up.Request(run["cwd"], target, name, "", [], checkout, prepare, tester=True)
    return up._claim(request, slots, repository)


def _initialize(claim: allocation.Claim, context: dict) -> allocation.Claim:
    record = dict(
        context,
        environment=allocation.content(claim),
        compose=bool(claim.compose),
        ports=list(claim.ports.values()),
        name=claim.live.name,
        target=claim.live.target,
        slot=claim.live.slot,
    )
    fd, temporary = tempfile.mkstemp(prefix=".tester-", dir=claim.data)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with os.fdopen(os.dup(fd), "w") as stream:
            json.dump(record, stream)
        # Publish complete ownership before the environment can reach a checkout.
        os.link(temporary, claim.data / RECORD)
    except BaseException:
        os.close(fd)
        raise
    finally:
        Path(temporary).unlink(missing_ok=True)
    return replace(claim, lease=fd)


def _deliver(root: Path, run: dict) -> None:
    slot = run["slot"]
    record = _record(Path(slot["state"]))
    checkout = Path(run["checkout"])
    with (checkout / allocation.ALLOCATION).open("x") as stream:
        stream.write(record["environment"])
    exclude = checkout / ".git/info/exclude"
    with exclude.open("a") as stream:
        stream.write("\n/.slot.env\n")
    (root / "run.json").write_text(json.dumps(run, indent=2) + "\n")


@contextmanager
def prepared(root: Path, run: dict, target: str | None):
    if not target:
        yield
        return
    claim = _claim(root, run, target)
    run["slot"] = {"state": str(claim.data), "fd": claim.lease, "compose": bool(claim.compose)}
    try:
        _deliver(root, run)
        compose._compose_up(claim, root / "evidence")
        yield
    except BaseException:
        if error := cleanup(root, run, preparation=True):
            run["slot_cleanup_error"] = error
        raise
    finally:
        os.close(run["slot"]["fd"])


def descriptors(run: dict) -> tuple[int, ...]:
    return (run["slot"]["fd"],) if "slot" in run else ()


def _idle(data: Path, record: dict) -> None:
    checkout = Path(record["run"]) / "checkout"
    if any(process.inside for process in occupants.census(str(checkout))):
        raise SlopmeisterError(f"a tester still occupies {checkout}; allocation retained")
    if record.get("compose"):
        allocation.remove_project(f"{record['target']}-slot{record['slot']}")
    if any(listener.port in record["ports"] for listener in allocation.bound_ports()):
        raise SlopmeisterError(
            f"a listener still holds tester ports; allocation retained at {data}"
        )


def _release(root: Path, slot: dict, preparation: bool = False) -> None:
    data = Path(slot["state"])
    record = _record(data)
    held, current = os.fstat(slot["fd"]), (data / RECORD).stat()
    if (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino):
        raise SlopmeisterError(f"tester allocation ownership changed: {data}")
    if record["run"] != str(root):
        raise SlopmeisterError(f"tester allocation belongs to another run: {data}")
    expected = record["environment"]
    environment = data / allocation.ALLOCATION
    checkout_file = root / "checkout" / allocation.ALLOCATION
    if environment.is_symlink() or (environment.exists() and environment.read_text() != expected):
        raise SlopmeisterError(f"tester allocation changed: {data}")
    if not preparation and (checkout_file.is_symlink() or checkout_file.read_text() != expected):
        raise SlopmeisterError(f"tester checkout allocation changed: {checkout_file}")
    if {path.name for path in data.iterdir()} - {RECORD, allocation.ALLOCATION}:
        raise SlopmeisterError(f"tester allocation contains unrelated files: {data}")
    _idle(data, record)
    environment.unlink(missing_ok=preparation)
    (data / RECORD).unlink()
    data.rmdir()


def cleanup(root: Path, run: dict, preparation: bool = False) -> str | None:
    if "slot" not in run:
        return None
    if run.get("process_stopped") is False:
        return "tester process stop unverified; slot allocation retained"
    try:
        _release(root, run["slot"], preparation)
    except (OSError, ValueError, KeyError, SlopmeisterError) as error:
        return str(error)
    return None


def find(target: str, name: str, wanted: str = "") -> Path | None:
    allocation.validate_name(target, "target")
    allocation.validate_name(name, "session")
    if wanted and (not wanted.isdigit() or len(wanted) > 2 or not 1 <= int(wanted) <= 99):
        raise SlopmeisterError("tester recovery requires a slot number from 1 to 99")
    state = allocation.state_path()
    paths = (
        [state / f"{target}-slot{wanted}" / RECORD]
        if wanted
        else state.glob(f"{target}-slot*/{RECORD}")
    )
    found = []
    for path in paths:
        if not os.path.lexists(path):
            continue
        try:
            record = _record(path.parent)
        except (OSError, ValueError, KeyError, TypeError, SlopmeisterError) as error:
            if wanted:
                raise SlopmeisterError(
                    f"unreadable tester ownership at {path}. Preserve it for repair"
                ) from error
            continue
        if record["name"] == name:
            found.append(path.parent)
        elif wanted:
            raise SlopmeisterError(f"tester allocation names '{record['name']}', not '{name}'")
    if len(found) > 1:
        raise SlopmeisterError(f"multiple tester allocations name '{name}', refusing")
    return found[0] if found else None


def recover(data: Path, repository: Path, wanted: str) -> None:
    fd = os.open(data / RECORD, os.O_RDWR | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SlopmeisterError(
                f"tester allocation is active; collect {_record(data)['run']}"
            ) from None
        record = _record(data)
        if repository != Path(record["repository"]) or wanted != str(record["slot"]):
            raise SlopmeisterError(
                "tester recovery requires its repository and exact --slot number"
            )
        root = Path(record["run"])
        unpublished = not os.path.lexists(root / "checkout" / allocation.ALLOCATION)
        _release(root, {"state": str(data), "fd": fd}, unpublished)
        print(f"slot: {record['target']}-slot{record['slot']} tester allocation released")
    finally:
        os.close(fd)


def live(repository: Path) -> list[allocation.Live]:
    found = []
    for path in sorted(allocation.state_path().glob(f"*-slot*/{RECORD}")):
        try:
            record = _record(path.parent)
        except (OSError, ValueError, KeyError, TypeError, SlopmeisterError) as error:
            print(f"slot: unreadable tester allocation at {path.parent}: {error}")
            continue
        if Path(record["repository"]) == repository:
            found.append(
                allocation.Live(
                    record["target"],
                    record["slot"],
                    record["name"],
                    Path(record["run"]) / "checkout",
                )
            )
    return found
