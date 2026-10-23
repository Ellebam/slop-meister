"""Root task notes stay out of wildcard staging, nested and ordinary markdown does not."""

from pathlib import Path

import pytest

from tests.integration.launch.helpers import ROOT, Machine, launch, machine, target
from tests.support.repos import git

RULE = "/*-NOTES.md"
NOTES = {"ISSUE-105-NOTES.md": "saved scope\n", "TASK-X-NOTES.md": "saved plan\n"}
INHERITED = b"/inherited-first/\n/inherited-last/"


def _source(path: Path, ignore: bytes) -> Path:
    repo = target(path)
    (repo / ".gitignore").write_bytes(ignore)
    (repo / "TRACKED-NOTES.md").write_text("tracked notes stay tracked\n")
    git(repo, "add", "-f", ".gitignore", "TRACKED-NOTES.md")
    git(repo, "commit", "-q", "-m", "source")
    return repo


def _clone(world: Machine, plot: str) -> tuple[Path, str, tuple[str, ...]]:
    """The product's own ignore file, with personal excludes switched off so they cannot mask it."""
    ignore = (ROOT / ".gitignore").read_bytes() + b"/unrelated-build-output/\n"
    source = _source(world.root / "source", ignore)
    git(world.root, "clone", "-q", str(source), "clone")
    return world.root / "clone", ".gitignore", ("-c", "core.excludesFile=/dev/null")


def _launched(world: Machine, plot: str) -> tuple[Path, str, tuple[str, ...]]:
    repo = _source(world.root / "repo", b"/target-cache/\n")
    launch(world, str(repo), plot, f"{plot}-notes")
    worktree = repo / ".worktrees" / f"{plot}-notes"
    return worktree, git(worktree, "config", "--get", "core.excludesFile").strip(), ()


@pytest.mark.parametrize(
    ("arrange", "plot"),
    [
        (_clone, "-"),
        (_launched, "example-client"),
        (_launched, "example-app"),
        (_launched, "slopmeister"),
    ],
    ids=["clone", "inject", "seed", "committed"],
)
def test_root_notes_never_staged(tmp_path, arrange, plot):
    """Bug: `git add -A` commits a session's private notes, or the rule hides nested markdown."""
    world = machine(tmp_path)
    (tmp_path / "ignore").write_bytes(INHERITED)
    (tmp_path / "gitconfig").write_text(f"[core]\n\texcludesFile = {tmp_path / 'ignore'}\n")
    worktree, source, options = arrange(world, plot)
    for name, text in {**NOTES, "ordinary.md": "ordinary\n", "docs/design-NOTES.md": "x\n"}.items():
        (worktree / name).parent.mkdir(exist_ok=True)
        (worktree / name).write_text(text)
    untracked = git(worktree, *options, "status", "--porcelain", "--untracked-files=all")
    assert untracked == "?? docs/design-NOTES.md\n?? ordinary.md\n"
    for wildcard in ("-A", "."):
        git(worktree, *options, "add", wildcard)
        assert (
            git(worktree, "diff", "--cached", "--name-only")
            == "docs/design-NOTES.md\nordinary.md\n"
        )
        git(worktree, "restore", "--staged", "--", "docs/design-NOTES.md", "ordinary.md")
    lines = (worktree / source).read_text().splitlines()
    assert lines.count(RULE) == 1
    for name, text in NOTES.items():
        origin = git(worktree, *options, "check-ignore", "-v", name)
        assert origin == f"{source}:{lines.index(RULE) + 1}:{RULE}\t{name}\n"
        assert (worktree / name).read_text() == text
    assert git(worktree, "ls-files", "--", "TRACKED-NOTES.md") == "TRACKED-NOTES.md\n"
    if arrange is _launched:
        assert (worktree / source).read_bytes().startswith(INHERITED + b"\n")
