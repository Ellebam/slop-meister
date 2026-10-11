"""Area plots use their declared repository when a brief names no source checkout."""

from pathlib import Path

import pytest

from tests.integration.install.installer_helpers import install
from tests.integration.launch.helpers import launch, machine, target
from tests.support.repos import git


def area_plot(root: Path, name: str, base: str, tasks: str) -> str:
    path = root / name / "plot.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        f'[plot]\nbase = "{base}"\n\n[target]\ntasks = "{tasks}"\n'
        f'\n[target.repository]\ncommit = "deny"\ndefault = "~/projects/{name}"\n'
        "\n[slots]\nnone = true\n"
    )
    return str(root)


@pytest.mark.parametrize(
    ("plot", "base", "tasks", "marker"),
    [
        ("example-notes", "freeform", "vault", "Always work in freeform mode."),
        ("example-client", "inject", "manual", "## The spine"),
    ],
)
def test_area_brief_without_repository_uses_default_worktree(tmp_path, plot, base, tasks, marker):
    """Bug: a repo-less area brief opened beside the dispatcher instead of in its own worktree."""
    world = machine(tmp_path)
    repo = target(Path(world.env["HOME"]) / "projects" / plot)
    plots = area_plot(tmp_path / "declared", plot, base, tasks)
    name = f"{plot}-default"
    output = launch(world, plot, name, "--tool", "codex", PLOT_DECLARATIONS=plots).stdout
    worktree = repo / ".worktrees" / name
    assert f"worktree ready at {worktree}" in output
    assert (worktree / ".git").is_file()
    instructions = (worktree / "AGENTS.md").read_text()
    assert marker in instructions
    assert "Agent commit permission for this plot is deny" in instructions
    assert (worktree / ".codex/rules/git-permission.rules").is_file()
    assert not (world.sessions / name).exists()


@pytest.mark.parametrize(
    ("exists", "message"),
    [(False, "target repository not found"), (True, "not a non-bare git repository")],
)
def test_area_default_refuses_an_unusable_clone_before_directory_preparation(
    tmp_path, exists, message
):
    """Bug: an absent or non-Git area clone silently fell back beside the dispatcher."""
    world = machine(tmp_path)
    plots = area_plot(tmp_path / "declared", "example-notes", "freeform", "vault")
    if exists:
        (Path(world.env["HOME"]) / "projects/example-notes").mkdir(parents=True)
    result = launch(
        world, "example-notes", "example-notes-missing", PLOT_DECLARATIONS=plots, ok=False
    )
    assert message in result.stderr
    assert not (world.sessions / "example-notes-missing").exists()


def test_explicit_directory_and_source_repo_override_the_area_default(tmp_path):
    """Bug: the default swallowed an operator's directory or owning-source choice."""
    world = machine(tmp_path)
    area = target(Path(world.env["HOME"]) / "projects/example-notes")
    source = target(tmp_path / "source")
    plots = area_plot(tmp_path / "declared", "example-notes", "freeform", "vault")
    launch(
        world, "example-notes", "example-notes-directory", "--directory", PLOT_DECLARATIONS=plots
    )
    assert (world.sessions / "example-notes-directory/AGENTS.md").is_file()
    assert not (
        world.sessions / "example-notes-directory/.codex/rules/git-permission.rules"
    ).exists()
    assert not (area / ".worktrees/example-notes-directory").exists()
    launch(world, str(source), "example-notes", "example-notes-source", PLOT_DECLARATIONS=plots)
    assert (source / ".worktrees/example-notes-source/.git").is_file()
    assert not (area / ".worktrees/example-notes-source").exists()


def test_redispatch_keeps_the_saved_directory_or_default_worktree(tmp_path):
    """Bug: adding a default made an existing Git-free worker unrecoverable."""
    world = machine(tmp_path)
    repo = target(Path(world.env["HOME"]) / "projects/example-notes")
    plots = area_plot(tmp_path / "declared", "example-notes", "freeform", "vault")
    launch(world, "example-notes", "example-notes-old", "--directory", PLOT_DECLARATIONS=plots)
    old = launch(
        world, "example-notes", "example-notes-old", "--redispatch", PLOT_DECLARATIONS=plots
    ).stdout
    assert f"existing workspace adopted at {world.sessions / 'example-notes-old'}" in old
    launch(world, "example-notes", "example-notes-new", PLOT_DECLARATIONS=plots)
    new = launch(
        world, "example-notes", "example-notes-new", "--redispatch", PLOT_DECLARATIONS=plots
    ).stdout
    assert f"existing workspace adopted at {repo / '.worktrees/example-notes-new'}" in new


def test_default_and_directory_refuse_the_other_shapes_session_name(tmp_path):
    """Bug: a directory and a default worktree could run with the same worker name."""
    world = machine(tmp_path)
    repo = target(Path(world.env["HOME"]) / "projects/example-notes")
    plots = area_plot(tmp_path / "declared", "example-notes", "freeform", "vault")
    launch(
        world, "example-notes", "example-notes-directory", "--directory", PLOT_DECLARATIONS=plots
    )
    rejected = launch(
        world, "example-notes", "example-notes-directory", PLOT_DECLARATIONS=plots, ok=False
    )
    assert "directory session already uses" in rejected.stderr
    assert not (repo / ".worktrees/example-notes-directory").exists()
    launch(world, "example-notes", "example-notes-worktree", PLOT_DECLARATIONS=plots)
    rejected = launch(
        world,
        "example-notes",
        "example-notes-worktree",
        "--directory",
        PLOT_DECLARATIONS=plots,
        ok=False,
    )
    assert "repository worktree already uses" in rejected.stderr
    assert not (world.sessions / "example-notes-worktree").exists()


def test_redispatch_refuses_a_preexisting_cross_shape_collision(tmp_path):
    """Bug: an old directory silently won over a same-name worktree on redispatch."""
    world = machine(tmp_path)
    repo = target(Path(world.env["HOME"]) / "projects/example-notes")
    plots = area_plot(tmp_path / "declared", "example-notes", "freeform", "vault")
    name = "example-notes-ambiguous"
    args = ("example-notes", name)
    launch(world, *args, "--directory", PLOT_DECLARATIONS=plots)
    worktree = repo / ".worktrees" / name
    worktree.parent.mkdir(exist_ok=True)
    git(repo, "worktree", "add", "-q", "-b", name, str(worktree))
    install(world.env, "--prepare", "example-notes", str(worktree), "--grant", str(world.vault))
    rejected = launch(world, *args, "--redispatch", PLOT_DECLARATIONS=plots, ok=False)
    assert "pass --directory or the repository path with --redispatch" in rejected.stderr
    directory = launch(world, *args, "--directory", "--redispatch", PLOT_DECLARATIONS=plots).stdout
    assert f"existing workspace adopted at {world.sessions / name}" in directory
    repository = launch(world, str(repo), *args, "--redispatch", PLOT_DECLARATIONS=plots).stdout
    assert f"existing workspace adopted at {worktree}" in repository
