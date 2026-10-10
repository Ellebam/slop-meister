"""Documentation paths and relative links resolve inside the repository."""

from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[3]
RENDERS = {
    "AGENTS.md": b"dist/codex/plots/slopmeister.md",
    "CLAUDE.md": b"dist/claude/plots/slopmeister.md",
}
ROOT_LINKS = tuple(RENDERS)


def _git(root: Path, *args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), *args], input=data, capture_output=True, check=True
    ).stdout


def _stage_symlink(root: Path, path: str, target: str) -> None:
    blob = _git(root, "hash-object", "-w", "--stdin", data=target.encode()).decode().strip()
    _git(root, "update-index", "--add", "--cacheinfo", f"120000,{blob},{path}")


def _tracked_regular_target(root: Path, target: bytes) -> bool:
    parts = target.split(b"/")
    unsafe = (
        target.startswith(b"/")
        or b"\0" in target
        or any(part in (b"", b".", b"..") for part in parts)
    )
    if unsafe:
        return False
    found = _git(
        root,
        "--literal-pathspecs",
        "ls-files",
        "-sz",
        "--",
        target.decode(errors="surrogateescape"),
    )
    records = [record for record in found.split(b"\0") if record]
    if len(records) != 1:
        return False
    metadata, path = records[0].split(b"\t", 1)
    mode, _, stage = metadata.split(b" ")
    return path == target and mode in (b"100644", b"100755") and stage == b"0"


def _root_symlink_errors(root: Path = ROOT) -> list[str]:
    errors = []
    for name in ROOT_LINKS:
        staged = _git(root, "ls-files", "-s", "--", name).rstrip(b"\n")
        if not staged:
            errors.append(f"not a tracked symlink: {name}")
            continue
        metadata, _ = staged.split(b"\t", 1)
        mode, oid, stage = metadata.split(b" ")
        if mode != b"120000" or stage != b"0":
            errors.append(f"not a tracked symlink: {name}")
            continue
        target = _git(root, "cat-file", "blob", oid.decode("ascii"))
        if not _tracked_regular_target(root, target):
            errors.append(
                f"missing tracked symlink target: {name}: {target.decode(errors='replace')}"
            )
    return errors


def _prose(text: str) -> list[str]:
    result, fence = [], None
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker and fence is None:
            fence = marker[1]
        elif marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
            fence = None
        result.append(line if fence is None and not marker else "")
    return result


def _anchors(path: Path) -> set[str]:
    result, counts = set(), {}
    for line in _prose(path.read_text()):
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*$", line)
        if not heading:
            continue
        label = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", heading[1])
        slug = re.sub(r"[^\w\- ]", "", label.lower()).replace(" ", "-")
        number = counts.get(slug, 0)
        counts[slug] = number + 1
        result.add(f"{slug}-{number}" if number else slug)
    return result


def _files() -> list[Path]:
    files = {ROOT / "README.md"}
    for pattern in (
        "docs/*.md",
        "src/skills/*/*.md",
        "plots/slopmeister/*.md",
        "plots/code/plot.md",
        "plots/freeform/plot.md",
        "plots/inject/*.md",
    ):
        files.update(ROOT.glob(pattern))
    return sorted(files)


def _literal_errors(file: Path) -> tuple[list[str], int]:
    missing, count = [], 0
    for token in re.findall(r"`([^`\n]+)`", file.read_text()):
        if any(char in token for char in "<>*{$ "):
            continue
        path = re.sub(r":[0-9]+(-[0-9]+)?$", "", token)
        known = path.startswith(("docs/", "src/", "plots/", "scripts/", "dist/"))
        if not known and path not in (
            "README.md",
            "AGENTS.md",
            "CLAUDE.md",
            "Taskfile.yml",
            ".gitignore",
        ):
            continue
        count += 1
        if not (ROOT / path).exists():
            missing.append(f"missing: {file.relative_to(ROOT)}: {token}")
    return missing, count


def _link_error(file: Path, line_number: int, destination: str) -> str | None:
    url = urlsplit(destination.strip("<>"))
    if url.scheme or url.netloc:
        return None
    target = (file.parent / unquote(url.path)).resolve() if url.path else file
    inside = target.is_relative_to(ROOT)
    relative = target.relative_to(ROOT).as_posix().rstrip("/") if inside else ""
    virtual = relative in (".claude/skills", ".agents/skills")
    if not inside or not target.exists() and not virtual:
        return f"missing link: {file.relative_to(ROOT)}:{line_number}: {destination}"
    if url.fragment and target.suffix == ".md" and unquote(url.fragment) not in _anchors(target):
        return f"missing anchor: {file.relative_to(ROOT)}:{line_number}: {destination}"
    return None


def _link_errors(file: Path) -> tuple[list[str], int]:
    in_skills = file.parent.parent == ROOT / "src/skills"
    if file != ROOT / "README.md" and file.parent != ROOT / "docs" and not in_skills:
        return [], 0
    errors, count = [], 0
    for number, line in enumerate(_prose(file.read_text()), 1):
        for destination in re.findall(r"\[[^]\n]*\]\(([^)\n]+)\)", line):
            count += 1
            if error := _link_error(file, number, destination):
                errors.append(error)
    return errors, count


def test_document_paths_and_relative_links_exist():
    errors, paths, links = _root_symlink_errors(), 0, 0
    for file in _files():
        literal_errors, literal_count = _literal_errors(file)
        link_errors, link_count = _link_errors(file)
        errors.extend(literal_errors + link_errors)
        paths += literal_count
        links += link_count
    assert not errors, "\n".join(errors)
    assert paths > 0 and links > 0


def test_root_links_point_at_their_own_tools_render():
    """Escaping bug: a root link aimed at the other tool's render passes the tracked-link check."""
    for name, render in RENDERS.items():
        metadata, _ = _git(ROOT, "ls-files", "-s", "--", name).split(b"\t", 1)
        assert _git(ROOT, "cat-file", "blob", metadata.split(b" ")[1].decode()) == render, name


def test_delivered_root_copies_cannot_mask_dangling_tracked_symlinks(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "README.md").write_text("`AGENTS.md` and [Claude](CLAUDE.md)\n")
    for name in ROOT_LINKS:
        (root / name).write_text("delivered copy\n")
        _stage_symlink(root, name, "missing.md")

    assert _root_symlink_errors(root) == [
        "missing tracked symlink target: AGENTS.md: missing.md",
        "missing tracked symlink target: CLAUDE.md: missing.md",
    ]


def test_root_symlink_errors_handle_missing_unsafe_and_literal_targets(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    assert _root_symlink_errors(root) == [
        "not a tracked symlink: AGENTS.md",
        "not a tracked symlink: CLAUDE.md",
    ]

    target = ":(top"
    (root / target).write_text("tracked\n")
    _git(root, "--literal-pathspecs", "add", "--", target)
    for name in ROOT_LINKS:
        _stage_symlink(root, name, target)
    assert _root_symlink_errors(root) == []

    target = "../outside.md"
    for name in ROOT_LINKS:
        _stage_symlink(root, name, target)
    assert _root_symlink_errors(root) == [
        f"missing tracked symlink target: {name}: {target}" for name in ROOT_LINKS
    ]
