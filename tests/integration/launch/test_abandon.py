"""Claim-free abandonment stops the delivered worker without changing its saved work."""

import json
import subprocess

import pytest

from slopmeister.claims import evidence
from tests.integration.launch.helpers import snapshot, target
from tests.support.claims_world import SLOPMEISTER, ClaimWorld
from tests.support.repos import git


@pytest.fixture
def world(tmp_path):
    world = ClaimWorld(tmp_path)
    try:
        yield world
    finally:
        world.close()


@pytest.fixture
def worker(world, request):
    tmp_path = world.root
    tool, tasks = request.param
    declaration = tmp_path / "plots/slopmeister/plot.toml"
    source = "manual" if tasks == "directory" else tasks
    declaration.write_text(declaration.read_text().replace('tasks="github"', f'tasks="{source}"'))
    name = "slopmeister-worker"
    process, workspace = world.worker(name, tool)
    args = (
        ["slopmeister", name, "--directory"]
        if tasks == "directory"
        else [str(world.repo), "slopmeister", name]
    )
    if tasks == "directory":
        world.env["PLOT_SESSION_ROOT"] = str(tmp_path / "sessions")
        workspace = tmp_path / "sessions" / name
        path = tmp_path / f"worker-{process.pid}.json"
        saved = json.loads(path.read_text())
        saved["workspace"] = str(workspace)
        path.write_text(json.dumps(saved))
    args += ["--tool", tool]

    def launch(*extra):
        return subprocess.run(
            [str(SLOPMEISTER / "bin/slopmeister"), "plot-session", *args, *extra],
            input="Mode: spine\nFixture work.\n",
            env=world.env,
            capture_output=True,
            text=True,
            timeout=90,
        )

    creation = [] if tasks == "directory" else ["--repository", str(target(tmp_path / "companion"))]
    result = launch(*creation)
    assert result.returncode == 0, result.stdout + result.stderr
    return world, process, workspace, launch


@pytest.mark.parametrize(
    "worker",
    [
        (tool, tasks)
        for tool in ("claude", "codex")
        for tasks in ("manual", "vault", "github", "directory")
    ],
    indirect=True,
)
def test_claim_free_abandon_keeps_workspace_and_never_touches_tracker(worker):
    world, process, workspace, launch = worker
    handoff = workspace / "SLOPMEISTER-NOTES.md"
    handoff.write_text("Saved work and recovery commands.\n")
    if (workspace / ".git").exists():
        (workspace / "work.txt").write_text("staged\n")
        git(workspace, "add", "work.txt")
        (workspace / "work.txt").write_text("staged\nunstaged\n")
        companion = workspace / ".slopmeister-repos/companion"
        (companion / "work.txt").write_text("companion work\n")
        branch = git(workspace, "branch", "--show-current")
        claim = evidence.receipt_path(workspace)
    else:
        branch, claim = "", workspace / ".slopmeister-config/issue.json"
    before = snapshot(workspace)
    result = launch("--abandon", "--handoff", str(handoff))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "predecessor closed" in result.stdout
    assert process.wait(timeout=5) != 0
    assert snapshot(workspace) == before and not claim.exists()
    if branch:
        assert git(workspace, "branch", "--show-current") == branch
        assert git(companion, "branch", "--show-current") == branch
    assert not (world.root / "github.log").exists()
    # A real fake-tracker request must be visible, so empty capture is meaningful.
    assert (
        subprocess.run(
            [
                str(world.bin / "gh"),
                "api",
                "--hostname",
                "github.com",
                "-X",
                "GET",
                "repos/owner/project/issues",
            ],
            env=world.env,
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )
    assert (world.root / "github.log").exists()


@pytest.mark.parametrize("worker", [("claude", "manual"), ("codex", "directory")], indirect=True)
@pytest.mark.parametrize(
    "invalid,diagnostic",
    [
        ("empty", "nonempty handoff"),
        ("outside", "inside the worker workspace"),
        ("symlink", "symlinked claim evidence path"),
        ("missing", "No such file or directory"),
        ("directory", "Is a directory"),
    ],
)
def test_invalid_handoff_keeps_claim_free_worker_alive(worker, invalid, diagnostic):
    world, process, workspace, launch = worker
    handoff = workspace / "SLOPMEISTER-NOTES.md"
    handoff.write_text("Saved work.\n")
    match invalid:
        case "empty":
            handoff.write_text(" \n")
        case "outside":
            handoff = world.root / "outside.md"
            handoff.write_text("Outside the worker.\n")
        case "symlink":
            link = workspace / "linked-notes.md"
            link.symlink_to(handoff)
            handoff = link
        case "missing":
            handoff.unlink()
        case "directory":
            handoff.unlink()
            handoff.mkdir()
    before = snapshot(workspace)
    result = launch("--abandon", "--handoff", str(handoff))
    assert result.returncode != 0 and diagnostic in result.stderr, result.stdout + result.stderr
    assert process.poll() is None and snapshot(workspace) == before
    assert not (world.root / "github.log").exists()
