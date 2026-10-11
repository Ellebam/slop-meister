"""Which files are handwritten, generated or data. Everything else here works on this list."""

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
import subprocess

from slopmeister.errors import SlopmeisterError

PYTHON = (
    "slopmeister/**/*.py",
    "tests/**/*.py",
    "scripts/**/*.py",
    "src/**/*.py",
    "plots/**/*.py",
    "host/**/*.py",
    "bin/slopmeister",
)
BASH = ("scripts/**/*.sh", "src/**/*.sh", "plots/**/*.sh", "plots/*/bin/*", "host/**/*.sh")
SOURCE = (
    "slopmeister/**",
    "tests/**",
    "bin/**",
    "scripts/**",
    "src/**",
    "plots/**",
    "host/ansible/**",
    "host/home-assistant/config/**",
)
GENERATED = ("dist/**",)
DATA = ("tests/data/**", "plots/**/fixtures/**")
IGNORED = (".venv/**", "**/__pycache__/**", "**/node_modules/**", "tmp/**")


@dataclass(frozen=True)
class Source:
    path: Path
    language: str


def _matches(relative: str, patterns: tuple[str, ...]) -> bool:
    return any(
        fnmatch(relative, pattern) or fnmatch(relative, pattern.replace("**/", ""))
        for pattern in patterns
    )


def committable(root: Path) -> list[str]:
    """Tracked and untracked-but-not-ignored paths present in the tree, links included."""
    if not (root / ".git").exists():
        found = (p for p in root.rglob("*") if p.is_file() or p.is_symlink())
        return sorted(str(p.relative_to(root)) for p in found)
    command = ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"]
    listing = subprocess.run(command, capture_output=True, text=True, check=False)
    if listing.returncode:
        raise SlopmeisterError(
            f"git ls-files failed: {listing.stderr.strip() or listing.returncode}"
        )
    # A tracked file deleted or moved in the working tree is not a source any more.
    names = listing.stdout.split("\0")
    return sorted(n for n in names if n and ((root / n).is_file() or (root / n).is_symlink()))


def tracked(root: Path) -> list[str]:
    """Tracked and untracked-but-not-ignored files, so a new file is judged before commit."""
    return [n for n in committable(root) if (root / n).is_file()]


KINDS = (
    ("ignored", IGNORED),
    ("generated", GENERATED),
    ("data", DATA),
    ("python", PYTHON),
    ("bash", BASH),
    ("source", SOURCE),
)


def classify(relative: str) -> str:
    """First matching kind wins, so data under scripts/ is data before it is Python."""
    path = Path(relative)
    if (
        relative in ("README.md", "host/README.md")
        or path.parent == Path("docs")
        and path.suffix == ".md"
    ):
        return "document"
    return next((kind for kind, patterns in KINDS if _matches(relative, patterns)), "other")


def sources(root: Path) -> list[Source]:
    """Handwritten runtime code and executable instructions governed by the budgets."""
    found = []
    for relative in tracked(root):
        kind = classify(relative)
        if kind in ("python", "bash", "source", "document"):
            found.append(Source(root / relative, kind))
    return found


def summary(root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for relative in tracked(root):
        kind = classify(relative)
        counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items()))
