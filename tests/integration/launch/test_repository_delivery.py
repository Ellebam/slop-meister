"""Companion delivery recovery and the saved push branch of each member."""

import shlex
import shutil
import subprocess

import pytest

from slopmeister.session import repositories as saved
from tests.integration.launch.helpers import CLI, declare, launch, machine, target
from tests.support.repos import git


@pytest.fixture
def changed_source(tmp_path):
    world = machine(tmp_path)
    app, service = target(tmp_path / "app"), target(tmp_path / "service with spaces")
    name = "example-app-recovery"
    source = tmp_path / "Slopmeister copy"
    for folder in ("bin", "src", "plots", "dist", "slopmeister"):
        shutil.copytree(
            CLI.parents[1] / folder, source / folder, ignore=shutil.ignore_patterns("__pycache__")
        )
    declare(tmp_path / "plots", "example-app", "committed")
    plots = source / "plots"
    declare(plots, "example-app", "committed")
    world.env["PLOT_DECLARATIONS"] = str(plots)
    binary = source / "bin/slopmeister"
    launch(world, str(app), "example-app", name, cli=str(binary))
    primary = app / ".worktrees" / name
    original = saved.read(primary)["source_identity"]
    (source / "slopmeister/change.py").write_text("# fixture source change\n")
    return world, app, service, name, plots, binary, primary, original


def test_changed_source_add_and_permission_recovery(tmp_path, changed_source):
    world, app, service, name, plots, binary, primary, original = changed_source

    def add(repo):
        return subprocess.run(
            [
                str(binary),
                "repository",
                "add",
                "--workspace",
                str(primary),
                "--repo",
                str(repo),
                "--push-branch",
                "mr-branch",
            ],
            env=world.env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    result = add(service)
    assert result.returncode != 0 and "session delivery differs" in result.stdout
    assert saved.read(primary)["source_identity"] == original
    assert not (primary / saved.DIRECTORY / service.name).exists()

    declare(plots, "example-app", "committed", commit="deny")
    other = target(tmp_path / "second companion")
    result = add(other)
    assert result.returncode and "plot permissions changed" in result.stdout
    assert "newly named worker" in result.stdout
    assert not (primary / saved.DIRECTORY / other.name).exists()
    assert not git(other, "for-each-ref", "refs/heads/" + name).strip()
    retry = shlex.split(result.stdout.partition("Retry from a matching checkout: ")[2].strip())
    assert retry == [
        "bin/slopmeister",
        "repository",
        "add",
        "--workspace",
        str(primary),
        "--repo",
        str(other),
        "--push-branch",
        "mr-branch",
    ]
    launch(
        world,
        str(app),
        "example-app",
        name + "-2",
        "--repository",
        str(service),
        "--repository",
        str(other),
        cli=str(binary),
    )
    replacement = app / ".worktrees" / (name + "-2")
    assert [row["repository"] for row in saved.members(replacement)] == list(
        map(str, (app, service, other))
    )
    assert len(saved.members(primary)) == 1
    # The untouched product checkout has the launch source and the original plot declaration.
    recovery = subprocess.run(
        retry,
        cwd=CLI.parents[1],
        env={**world.env, "PLOT_DECLARATIONS": str(tmp_path / "plots")},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert recovery.returncode == 0, recovery.stdout + recovery.stderr


def status_pushes(world, primary):
    status = subprocess.run(
        [str(CLI), "repository", "status", "--workspace", str(primary)],
        env=world.env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return [line.rsplit(" ", 1)[1] for line in status.stdout.splitlines()]


def test_push_branches_are_recorded_per_repository_and_kept_on_redispatch(tmp_path):
    """Bug: a suffixed worktree or a companion pushes to its local name, not its merge request."""
    world = machine(tmp_path)
    declare(tmp_path / "plots", "example-app", "committed")
    app, service = target(tmp_path / "app"), target(tmp_path / "service")
    args = [str(app), "example-app", "example-app-push-2"]
    pushes = [
        "--push-branch",
        str(app),
        "example-app-push",
        "--push-branch",
        str(service),
        "mr-svc",
    ]
    launch(world, *args, "--repository", str(service), *pushes)
    primary = app / ".worktrees/example-app-push-2"
    launch(world, *args, "--redispatch")
    assert status_pushes(world, primary) == ["push=example-app-push", "push=mr-svc"]
    declare(tmp_path / "plots", "example-app", "committed", commit="deny")
    command = [str(CLI), "repository", "add", "--workspace", str(primary), "--repo", str(service)]
    for branch in ("mr-new", "mr-new", "mr-second", "-bad"):
        result = subprocess.run(
            [*command, "--push-branch=" + branch],
            env=world.env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if branch == "-bad":
            assert result.returncode and "valid branch name" in result.stdout
        else:
            assert result.returncode == 0 and "push branch updated" in result.stdout
    declare(tmp_path / "plots", "example-app", "committed")
    launch(world, *args, "--redispatch")
    assert status_pushes(world, primary) == ["push=example-app-push", "push=mr-second"]


def test_redispatch_records_the_push_branch_of_an_existing_worker(tmp_path):
    """Bug: a worker launched without --push-branch pushes to a stray branch named after its
    worktree, and only a fresh launch could name its merge request branch."""
    world = machine(tmp_path)
    declare(tmp_path / "plots", "example-app", "committed")
    app, service = target(tmp_path / "app"), target(tmp_path / "service")
    args = [str(app), "example-app", "example-app-push-2"]
    launch(world, *args, "--repository", str(service))
    primary = app / ".worktrees/example-app-push-2"
    assert status_pushes(world, primary) == ["push=example-app-push-2", "push=example-app-push-2"]
    launch(world, *args, "--redispatch", "--push-branch", str(app), "example-app-push")
    launch(world, *args, "--redispatch")
    assert status_pushes(world, primary) == ["push=example-app-push", "push=example-app-push-2"]
    companion = launch(world, *args, "--redispatch", "--push-branch", str(service), "x", ok=False)
    assert "repository add" in companion.stdout + companion.stderr
    invalid = launch(world, *args, "--redispatch", "--push-branch", str(app), "-x", ok=False)
    assert "not a valid branch name" in invalid.stdout + invalid.stderr
    assert status_pushes(world, primary) == ["push=example-app-push", "push=example-app-push-2"]


def test_push_branch_for_a_repository_outside_the_launch_is_refused(tmp_path):
    world = machine(tmp_path)
    declare(tmp_path / "plots", "example-app", "committed")
    app, other = target(tmp_path / "app"), target(tmp_path / "other")
    result = launch(
        world, str(app), "example-app", "example-app-x", "--push-branch", str(other), "b", ok=False
    )
    assert "outside this launch" in result.stdout + result.stderr
    assert not (app / ".worktrees/example-app-x").exists()
