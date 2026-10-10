"""A launch copies its agreement and procedures from the checkout that runs it, never from main."""

from pathlib import Path

import pytest

from tests.integration.install.installer_helpers import checkout
from tests.integration.launch.helpers import (
    codex_writable,
    declare,
    launch,
    machine,
    target,
    temporary_roots,
)
from tests.support.repos import git


def _new_skill(root: Path) -> str:
    """A procedure that exists only on the invoking branch."""
    with (root / "dist/manifest.tsv").open("a") as stream:
        stream.write("skill\tbranch-only\tshared\tfalse\tfalse\n")
    for tool in ("claude", "codex"):
        skill = root / f"dist/{tool}/skills/branch-only/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(f"branch payload for {tool}\n")
    return "skills/branch-only/SKILL.md"


def _changed_target_skill(root: Path) -> str:
    """A target procedure the invoking branch changed."""
    for tool in ("claude", "codex"):
        with (root / f"dist/{tool}/targets/example-app/skills/example-check/SKILL.md").open(
            "a"
        ) as stream:
            stream.write("\nworktree procedure\n")
    return "targets/example-app/skills/example-check/SKILL.md"


def _branch(path: Path, plot: str, arrange) -> tuple[Path, str]:
    """A scratch checkout whose rendered payload differs from the checkout running the tests."""
    branch = checkout(path)
    source = arrange(branch)
    for tool in ("claude", "codex"):
        with (branch / f"dist/{tool}/plots/{plot}.md").open("a") as stream:
            stream.write("\nworktree snapshot\n")
    return branch, source


def _original(path: Path) -> Path:
    repo = target(path)
    (repo / "AGENTS.md").write_text("original agreement\n")
    git(repo, "add", "AGENTS.md")
    git(repo, "commit", "-q", "-m", "original")
    return repo


def _commit_application(worktree: Path) -> None:
    """A clean snapshot lets an application commit through without entering its history."""
    assert git(worktree, "status", "--porcelain", "--untracked-files=all") == ""
    (worktree / "app.txt").write_text("application\n")
    git(worktree, "add", "-A")
    git(worktree, "commit", "-q", "-m", "application")
    assert git(worktree, "show", "HEAD:AGENTS.md") == "original agreement\n"


@pytest.mark.parametrize(
    ("plot", "delivery", "arrange"),
    [("example-client", "inject", _new_skill), ("example-app", "seed", _changed_target_skill)],
    ids=["inject", "seed"],
)
def test_invoking_checkout_owns_snapshot(tmp_path, plot, delivery, arrange):
    """Bug: main's render leaks into a branch launch, the snapshot enters application history,
    or a downstream launch grants write access to the upstream repository."""
    world = machine(tmp_path)
    branch, source = _branch(tmp_path / "branch", plot, arrange)
    repo = _original(tmp_path / "repo")
    before = git(repo, "rev-parse", "HEAD")
    name = f"{plot}-snapshot"
    declared = str(declare(tmp_path / "plots", plot, delivery))
    cli = str(branch / "bin/slopmeister")
    result = launch(
        world, str(repo), plot, name, "--tool", "codex", cli=cli, PLOT_DECLARATIONS=declared
    )
    worktree = repo / ".worktrees" / name
    delivered = source.removeprefix(f"targets/{plot}/")
    for tool, native, agreement in (
        ("claude", ".claude", "CLAUDE.md"),
        ("codex", ".agents", "AGENTS.md"),
    ):
        render = (branch / f"dist/{tool}/plots/{plot}.md").read_bytes()
        assert (worktree / agreement).read_bytes().startswith(render + b"\n")
        assert (worktree / native / delivered).read_bytes() == (
            branch / f"dist/{tool}" / source
        ).read_bytes()
    assert codex_writable(worktree) == {str(world.vault.resolve()), *temporary_roots(world)}
    assert "--add-dir" not in result.stdout
    _commit_application(worktree)
    assert git(repo, "rev-parse", "HEAD") == before
    assert git(repo, "status", "--porcelain", "--untracked-files=all") == ""
