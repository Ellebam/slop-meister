"""Test processes carry their run folder, and a run ends when the gate named in it exits."""

import contextlib
import ctypes
from datetime import UTC, datetime
import itertools
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time

from slopmeister.removal import remove_tree

ROOT_VARIABLE = "SLOPMEISTER_TEST_ROOT"
STOP_GRACE, PS_TIMEOUT, RUN_ROOT = 2, 5, Path("/tmp").resolve()
_KERN_PROCARGS2 = (1, 49)


def utc() -> str:
    return datetime.now(UTC).isoformat()


class _BSDInfo(ctypes.Structure):
    _fields_ = [
        ("header", ctypes.c_uint32 * 12),
        ("names", ctypes.c_char * 48),
        ("details", ctypes.c_uint32 * 6),
        ("seconds", ctypes.c_uint64),
        ("microseconds", ctypes.c_uint64),
    ]


def _darwin_process(pid: int) -> tuple[str | None, int | None]:
    info = _BSDInfo()
    size = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True).proc_pidinfo(
        pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info)
    )
    if size == 0 and ctypes.get_errno() == 3:
        return None, None
    if size != ctypes.sizeof(info):
        raise OSError(ctypes.get_errno(), f"cannot inspect test process {pid}")
    birth = None if info.header[1] == 5 else f"{info.seconds}:{info.microseconds}"
    return (None, None) if birth is None else (birth, int(info.details[1]))


def _process(pid: int) -> tuple[str | None, int | None]:
    if sys.platform == "darwin":
        return _darwin_process(pid)
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return (None, None) if fields[0] == "Z" else (fields[19], int(fields[2]))
    except FileNotFoundError:
        return None, None


def identity(pid: int) -> str | None:
    return _process(pid)[0]


def new_run() -> tuple[Path, dict]:
    """A job folder whose owner.json names this process as the gate that owns the run."""
    root = Path(tempfile.mkdtemp(prefix="htr.", dir=RUN_ROOT))
    record = {"root": str(root), "pid": os.getpid(), "identity": identity(os.getpid())}
    (root / "owner.json").write_text(json.dumps(record) + "\n")
    return root, record


def _environ(pid: int, buffer: ctypes.Array) -> list[bytes]:
    """The exact environment, never the ps text where arguments and variables mix."""
    if sys.platform != "darwin":
        with open(f"/proc/{pid}/environ", "rb") as stream:
            return stream.read().split(b"\0")
    mib = (ctypes.c_int * 3)(*_KERN_PROCARGS2, pid)
    size = ctypes.c_size_t(len(buffer))
    libc = ctypes.CDLL("/usr/lib/libc.dylib", use_errno=True)
    if libc.sysctl(mib, 3, buffer, ctypes.byref(size), None, 0) != 0:
        raise OSError(ctypes.get_errno(), f"cannot read environment of {pid}")
    data = buffer.raw[: size.value]
    argc, rest = int.from_bytes(data[:4], sys.byteorder), data[4:]
    start = rest.find(b"\0")
    while 0 <= start < len(rest) and rest[start] == 0:
        start += 1
    # A skipped empty argv entry shifts later, so arguments are never read as variables.
    return list(itertools.takewhile(bool, rest[start:].split(b"\0")[argc:]))


def named_folders(value: str) -> set[Path]:
    """Run folders a marker chain names, including paths below a folder."""
    folders = set()
    for part in filter(None, value.split(":")):
        path = Path(os.path.normpath(part))
        for candidate in (path, *path.parents):
            if candidate.parent == RUN_ROOT and candidate.name.startswith("htr."):
                folders.add(RUN_ROOT / candidate.name)
    return folders


def run_processes() -> list[tuple[int, str, set[Path]]]:
    """This user's processes whose marker or TMPDIR names a run folder, with birth identity."""
    rows = subprocess.run(
        ["ps", "-axo", "pid=,uid="], capture_output=True, text=True, check=True, timeout=PS_TIMEOUT
    ).stdout.split()
    buffer, found = ctypes.create_string_buffer(os.sysconf("SC_ARG_MAX")), []
    # Tools such as Codex pass their children a stripped environment that keeps TMPDIR.
    markers = (ROOT_VARIABLE.encode() + b"=", b"TMPDIR=")
    for pid_text, uid in itertools.batched(rows, 2, strict=True):
        pid = int(pid_text)
        if int(uid) != os.getuid() or pid == os.getpid():
            continue
        try:
            birth, environment = identity(pid), _environ(pid, buffer)
        except OSError:
            continue
        values = [e.split(b"=", 1)[1] for e in environment if e.startswith(markers)]
        folders = set().union(*(named_folders(v.decode(errors="replace")) for v in values))
        if birth and folders and identity(pid) == birth:
            found.append((pid, birth, folders))
    return found


def _signal(pid: int, birth: str, signum: signal.Signals) -> None:
    if identity(pid) == birth:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signum)


def stop_processes(targets: list[tuple[int, str]]) -> list[int]:
    """SIGTERM, then SIGKILL, each only after the birth identity is rechecked."""
    for signum in (signal.SIGTERM, signal.SIGKILL):
        for pid, birth in targets:
            _signal(pid, birth, signum)
        deadline = time.monotonic() + STOP_GRACE
        while targets and time.monotonic() < deadline:
            targets = [(pid, birth) for pid, birth in targets if identity(pid) == birth]
            time.sleep(0.02)
    return [pid for pid, birth in targets if identity(pid) == birth]


def stop_run(folder: Path) -> None:
    targets = [(pid, birth) for pid, birth, folders in run_processes() if folder in folders]
    if survivors := stop_processes(targets):
        raise RuntimeError(f"test processes of {folder} still active: {survivors}")


def _owner(folder: Path) -> dict | None:
    """The owner record of a real, private run folder, never through a link."""
    try:
        info, owner = folder.lstat(), (folder / "owner.json").lstat()
        if not (stat.S_ISDIR(info.st_mode) and stat.S_ISREG(owner.st_mode)):
            return None
        if info.st_uid != os.getuid() or owner.st_uid != os.getuid():
            return None
        record = json.loads((folder / "owner.json").read_text())
    except OSError, ValueError:
        return None
    return record if isinstance(record, dict) and type(record.get("pid")) is int else None


def ended(folder: Path) -> bool:
    if not os.path.lexists(folder):
        return True
    owner = _owner(folder)
    if owner is None:
        return False
    current = identity(owner["pid"])
    return current is None or bool(owner.get("identity")) and current != owner["identity"]


def remove(folder: Path) -> None:
    """Contents first and owner.json last, so an interrupted removal stays provably ours."""
    for child in folder.iterdir():
        if child.name == "owner.json":
            continue
        if child.is_dir() and not child.is_symlink():
            remove_tree(child)
        else:
            child.unlink()
    (folder / "owner.json").unlink()
    folder.rmdir()


def clean() -> tuple[int, int]:
    """Stop processes of ended runs, then remove ended folders no process names."""
    leftovers = [
        (pid, birth) for pid, birth, folders in run_processes() if all(map(ended, folders))
    ]
    stop_processes(leftovers)
    named = set().union(*(folders for _, _, folders in run_processes()))
    removed = 0
    for folder in RUN_ROOT.glob("htr.*"):
        if folder not in named and ended(folder):
            # A concurrent gate start may be removing the same ended folder.
            with contextlib.suppress(FileNotFoundError):
                remove(folder)
            removed += 1
    return len(leftovers), removed
