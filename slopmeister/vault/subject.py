"""Immutable directory subjects shared by review and independent testing."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile


@dataclass(frozen=True)
class SubjectFile:
    path: str
    ranges: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class DirectorySubject:
    manifest: Path
    root: Path
    files: tuple[SubjectFile, ...]
    tree_sha256: str
    manifest_sha256: str

    @property
    def identity(self) -> str:
        return hashlib.sha256(
            json.dumps(
                [self.manifest_sha256, self.tree_sha256],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()


def no_symlink_chain(path: Path, label: str) -> None:
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError(f"{label} must not use a symlink")


def relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or not value.isprintable():
        raise ValueError("subject path must be a printable relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("subject path escapes its root")
    return str(path)


def ranges(value: object) -> tuple[tuple[int, int], ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("subject ranges must be a list")
    result = []
    for item in value:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or any(type(number) is not int for number in item)
            or item[0] < 1
            or item[1] < item[0]
        ):
            raise ValueError("subject range must be [first, last] positive line numbers")
        if result and item[0] <= result[-1][1]:
            raise ValueError("subject ranges must be ordered and non-overlapping")
        result.append((item[0], item[1]))
    return tuple(result)


def tree_digest(root: Path) -> str:
    """Hash the full tree shape, modes, symlink targets and regular-file bytes."""
    no_symlink_chain(root, "subject root")
    root = root.resolve(strict=True)
    if not root.is_dir() or root == root.parent:
        raise ValueError("subject root must be an existing non-root directory")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        name = path.relative_to(root).as_posix().encode()
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        kind, content = _tree_entry(path)
        digest.update(name + b"\0" + kind + f"{mode:o}".encode() + b"\0")
        digest.update(hashlib.sha256(content).digest())
    return digest.hexdigest()


def _tree_entry(path: Path) -> tuple[bytes, bytes]:
    if path.is_symlink():
        return b"L", os.fsencode(os.readlink(path))
    if path.is_file():
        return b"F", path.read_bytes()
    return (b"D", b"") if path.is_dir() else (b"O", b"")


def _manifest(path: Path | str) -> tuple[Path, dict]:
    manifest = Path(path)
    if not manifest.is_absolute():
        raise ValueError("subject manifest path must be absolute")
    no_symlink_chain(manifest, "subject manifest")
    manifest = manifest.resolve(strict=True)
    if not manifest.is_file():
        raise ValueError("subject manifest must be a regular file")
    data = json.loads(manifest.read_text())
    if not isinstance(data, dict) or set(data) != {"version", "root", "files", "tree_sha256"}:
        raise ValueError("subject manifest has unknown or missing fields")
    if data["version"] != 1 or not isinstance(data["files"], list) or not data["files"]:
        raise ValueError("subject manifest version or files are invalid")
    return manifest, data


def _subject_file(root: Path, item: object) -> SubjectFile:
    if not isinstance(item, dict) or set(item) - {"path", "ranges"}:
        raise ValueError("subject file entry is invalid")
    name = relative_path(item.get("path"))
    source = root / name
    no_symlink_chain(source, "declared subject input")
    if not source.is_file() or not source.resolve().is_relative_to(root):
        raise ValueError("declared subject input must be a regular file inside the root")
    return SubjectFile(name, ranges(item.get("ranges")))


def load(path: Path | str, *, verify: bool = True) -> DirectorySubject:
    manifest, data = _manifest(path)
    root = Path(data["root"])
    if not root.is_absolute():
        raise ValueError("subject root must be absolute")
    no_symlink_chain(root, "subject root")
    root = root.resolve(strict=True)
    if manifest.is_relative_to(root):
        raise ValueError("subject manifest must live outside the subject")
    files = [_subject_file(root, item) for item in data["files"]]
    if len({item.path for item in files}) != len(files):
        raise ValueError("subject paths must be unique")
    digest = tree_digest(root)
    if verify and data["tree_sha256"] != digest:
        raise ValueError("directory subject changed after it was frozen")
    if not isinstance(data["tree_sha256"], str) or len(data["tree_sha256"]) != 64:
        raise ValueError("subject tree digest is invalid")
    return DirectorySubject(
        manifest,
        root,
        tuple(files),
        data["tree_sha256"],
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
    )


def freeze(root: Path, files: list[dict], destination: Path) -> DirectorySubject:
    """Write one canonical immutable subject manifest outside its source tree."""
    root = root.resolve(strict=True)
    payload = {"version": 1, "root": str(root), "files": files, "tree_sha256": tree_digest(root)}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    return load(destination)


def copy_regular(source: Path, target: Path) -> None:
    """Copy one regular file without following a source or destination symlink."""
    target.parent.mkdir(parents=True, exist_ok=True)
    source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(source_fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("declared input changed type before copy")
        target_fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.fchmod(target_fd, stat.S_IMODE(info.st_mode))
        with os.fdopen(source_fd, "rb") as source_stream:
            source_fd = -1
            with os.fdopen(target_fd, "wb") as target_stream:
                shutil.copyfileobj(source_stream, target_stream)
    finally:
        if source_fd >= 0:
            os.close(source_fd)


def copy_inputs(subject: DirectorySubject, destination: Path) -> None:
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    for item in subject.files:
        copy_regular(subject.root / item.path, destination / item.path)


def isolated_copy(subject: DirectorySubject):
    """Return a temporary exact-input copy; the caller owns the context."""
    temporary = tempfile.TemporaryDirectory(prefix="slopmeister-subject-")
    root = Path(temporary.name).resolve() / "subject"
    copy_inputs(subject, root)
    return temporary, root


def scope_lines(subject: DirectorySubject) -> tuple[str, ...]:
    result = []
    for item in subject.files:
        suffix = (
            ""
            if not item.ranges
            else " lines " + ", ".join(f"{first}-{last}" for first, last in item.ranges)
        )
        result.append(item.path + suffix)
    return tuple(result)
