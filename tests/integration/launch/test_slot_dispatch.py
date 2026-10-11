"""Slot-required refusals leave a worker launch easy to correct."""

import json
from pathlib import Path
import shlex
import subprocess

import pytest

from tests.integration.launch.helpers import (
    ROOT,
    declare,
    executable,
    launch,
    launch_here,
    machine,
    reported,
    snapshot,
    target,
)
from tests.support.repos import git

SPINE = "Mode: spine\n\nImplement the fixture."


def _world(tmp_path, source="stdin", tool="claude"):
    world = machine(tmp_path)
    repo = target(tmp_path / "repo space 'quote $dollar")
    plots = declare(tmp_path / "plots", "example-app", "inject", commit="deny", tasks="github")
    plot = plots / "example-app/plot.toml"
    text = plot.read_text().replace(
        'commit = "deny"', f'commit = "deny"\ndefault = {json.dumps(str(repo))}'
    )
    if tool == "opencode":
        text = text.replace('commit = "deny"', 'commit = "allow"\nshipping = "allow"')
    plot.write_text(text.replace("none = true", "max = 6\n\n[slots.ports]\nKEK_PORT = 18780"))
    world.env["SLOT_STATE_DIR"] = str(tmp_path / "slots")
    executable(tmp_path / "bin/opencode", "#!/bin/sh\nexit 0\n")
    flags = ["--issue-id", "7"] if source == "issue-id" else []
    if source == "issue":
        executable(tmp_path / "bin/gh", "#!/bin/sh\nprintf 'Mode: spine\\r\\nFixture\\r\\n'\n")
        flags = ["--issue", "7"]
    elif source == "note":
        plot.write_text(plot.read_text().replace('tasks = "github"', 'tasks = "vault"'))
        (world.vault / "brief.md").write_text(SPINE)
        flags = ["--note", "brief.md"]
    return world, repo, flags


@pytest.mark.parametrize("tool", ["claude", "codex", "opencode"])
@pytest.mark.parametrize("source", ["stdin", "issue-id", "issue", "note"])
def test_spine_slot_refusal_preserves_workspace_and_fetch_options(
    tmp_path, tool, source, monkeypatch, capsys
):
    """Bug: an unslotted spine worker starts, or its correction loses the kickoff fetcher."""
    world, repo, source_flags = _world(tmp_path, source, tool)
    # Claim preflight has separate fixtures. This test exercises slot and kickoff validation.
    monkeypatch.setattr("slopmeister.launch.issue.claim", lambda _: None)
    flags = ["--tool", tool, *source_flags]
    before = snapshot(repo), snapshot(world.claude), snapshot(world.codex)
    worker = (str(repo), "example-app", "example-app-refused", *flags)
    assert launch_here(monkeypatch, world, *worker, kickoff=SPINE) != 0
    stderr = capsys.readouterr().err
    assert "requires a slot for Mode: spine" in stderr
    assert "No worktree or worker was created" in stderr
    retry = stderr.split("Retry: ", 1)[1].splitlines()[0]
    prefix = ["task", "slot:up", "--", str(repo)]
    assert shlex.split(retry) == [*prefix, "example-app", "example-app-refused", *flags]
    assert (snapshot(repo), snapshot(world.claude), snapshot(world.codex)) == before
    assert not world.state.exists() and not Path(world.env["SLOT_STATE_DIR"]).exists()
    assert git(repo, "branch", "--list", "example-app-refused") == ""
    assert ("same kickoff on stdin" in stderr) is (source in ("stdin", "issue-id"))


def test_printed_slot_retry_keeps_name_default_repository_and_native_tail(tmp_path):
    """Bug: correcting the launcher requires cleanup or loses a quoted native argument."""
    world, repo, _ = _world(tmp_path)
    flags = ["--tool", "codex", "--model", "fixture-model"]
    flags += ["--", "-c", 'model_reasoning_effort="high"']
    result = launch(world, "example-app", "example-app-retry", *flags, kickoff=SPINE, ok=False)
    retry = result.stderr.split("Retry: ", 1)[1].splitlines()[0]
    assert "Append the original native tool arguments after --" in result.stderr
    assert 'model_reasoning_effort="high"' not in retry
    executable(tmp_path / "bin/lsof", "#!/bin/sh\nexit 0\n")
    executable(tmp_path / "bin/docker", "#!/bin/sh\nexit 1\n")
    corrected = subprocess.run(
        [*shlex.split(retry), *flags[4:]],
        cwd=ROOT,
        env=world.env,
        input=SPINE,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert corrected.returncode == 0, corrected.stdout + corrected.stderr
    worktree = repo / ".worktrees/example-app-retry"
    assert "KEK_PORT=18781\n" in (worktree / ".slot.env").read_text()
    assert (worktree / "AGENTS.md").is_file()
    assert 'model_reasoning_effort="high"' in corrected.stdout
    assert "fixture-model" in corrected.stdout
    assert (
        Path(reported(corrected.stdout, "kickoff file")).read_text()
        == f"example-app-retry\n\n{SPINE}\n"
    )


def test_saved_slot_redispatch_keeps_its_allocation(tmp_path):
    """Bug: the new slot guard prevents replacing a worker in its already slotted workspace."""
    world, repo, _ = _world(tmp_path)
    allocation = tmp_path / ".slot.env"
    allocation.write_text("SLOT=1\nKEK_PORT=18781\n")
    args = str(repo), "example-app", "example-app-saved"
    launch(world, *args, PLOT_SESSION_WORKTREE_FILE=str(allocation))
    worktree = repo / ".worktrees/example-app-saved"
    saved = (worktree / ".slot.env").read_bytes()
    launch(world, *args, "--redispatch", kickoff=SPINE)
    assert (worktree / ".slot.env").read_bytes() == saved


@pytest.mark.parametrize("brief", ["Mode: freeform\n\nMode: spine", "legacy kickoff"])
def test_freeform_and_undeclared_mode_keep_plain_launch(tmp_path, brief):
    """Bug: the spine-only slot guard rejects freeform or legacy briefs."""
    world, repo, _ = _world(tmp_path)
    launch(world, str(repo), "example-app", "example-app-plain", kickoff=brief)
    assert not (repo / ".worktrees/example-app-plain/.slot.env").exists()


def test_directory_spine_and_resource_free_spine_keep_plain_launch(tmp_path):
    """Bug: a resource requirement leaks into directory sessions or resource-free plots."""
    world, repo, _ = _world(tmp_path)
    launch(world, "example-app", "example-app-directory", "--directory", kickoff=SPINE)
    assert (world.sessions / "example-app-directory/AGENTS.md").is_file()
    launch(world, str(repo), "example-client", "example-client-spine", kickoff=SPINE)
    assert (repo / ".worktrees/example-client-spine/AGENTS.md").is_file()


def test_unrelated_staged_file_does_not_satisfy_slot_requirement(tmp_path):
    """Bug: a generic staged launcher file silently substitutes for a slot allocation."""
    world, repo, _ = _world(tmp_path)
    staged = tmp_path / "brief.txt"
    staged.write_text("not an allocation\n")
    result = launch(
        world,
        str(repo),
        "example-app",
        "example-app-unallocated",
        kickoff=SPINE,
        ok=False,
        PLOT_SESSION_WORKTREE_FILE=str(staged),
    )
    assert "requires a slot" in result.stderr
    assert not (repo / ".worktrees").exists()


def test_slot_retry_omits_native_argument_values(tmp_path):
    """Bug: refusing a slot-required launch echoes its native argument values."""
    world, repo, _ = _world(tmp_path)
    configuration = 'model_providers.fixture.experimental_bearer_token="VALUE"'
    secret = "opaque-fixture-value"
    tail = ["--tool", "codex", "--", "-c", configuration.replace("VALUE", secret)]
    result = launch(
        world, str(repo), "example-app", "example-app-secret", *tail, kickoff=SPINE, ok=False
    )
    assert "requires a slot" in result.stderr
    assert secret not in result.stderr
    assert "Append the original native tool arguments after --" in result.stderr
    retry = result.stderr.split("Retry: ", 1)[1].splitlines()[0]
    assert shlex.split(retry)[:2] == ["task", "slot:up"]
    assert "model_providers" not in retry
    assert not (repo / ".worktrees").exists()


@pytest.mark.parametrize("metadata", ["name", "repository", "note"])
def test_retry_keeps_task_word_metadata_verbatim(tmp_path, metadata):
    """Bug: a credential regex mistakes task-* names, paths and notes for a token."""
    world, repo, flags = _world(tmp_path, "note" if metadata == "note" else "stdin")
    name = "example-app-9-task-storage-and-copy"
    if metadata == "repository":
        old = repo
        repo = repo.with_name("task-storage-and-copy")
        old.rename(repo)
    if metadata == "note":
        (world.vault / "brief.md").rename(world.vault / "task-storage-and-copy.md")
        flags = ["--note", "task-storage-and-copy.md"]
    result = launch(world, str(repo), "example-app", name, *flags, kickoff=SPINE, ok=False)
    retry = result.stderr.split("Retry: ", 1)[1].splitlines()[0]
    assert shlex.split(retry) == ["task", "slot:up", "--", str(repo), "example-app", name, *flags]
    assert "[REDACTED]" not in result.stderr


@pytest.mark.parametrize("tool", ["claude", "codex", "opencode"])
@pytest.mark.parametrize(
    "prefix", ["\n\n", "Title\u2028more\n\n", "Title\fmore\n\n", "Title\rmore\n\n"]
)
def test_source_mode_within_checker_window_requires_slot(tmp_path, tool, prefix):
    """Bug: Codex's added name header pushes an accepted source mode past the guard window."""
    world, repo, _ = _world(tmp_path, tool=tool)
    brief = prefix + SPINE
    checked = subprocess.run(
        [str(ROOT / "bin/slopmeister"), "kickoff", "-"],
        input=brief,
        env=world.env,
        text=True,
        capture_output=True,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
    result = launch(
        world,
        str(repo),
        "example-app",
        "example-app-window",
        "--tool",
        tool,
        kickoff=brief,
        ok=False,
    )
    assert "requires a slot" in result.stderr
    assert not (repo / ".worktrees").exists()
