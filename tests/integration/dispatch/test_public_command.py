"""The Task dispatcher path prepares both tools without touching operator state."""

import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from slopmeister.dispatch import command
from tests.integration.launch.helpers import ROOT, codex_writable, machine, temporary_roots


def _run(world, *args, **extra):
    state = str(world.root / "dispatch")
    env = dict(world.env, DISPATCH_NO_LAUNCH="1", DISPATCH_STATE_DIR=state, **extra)
    env.pop("SLOPMEISTER_SECRET_BROKER", None)
    return subprocess.run(
        ["task", "dispatch", "--", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _reported(output, label):
    return Path(next(line.split(": ", 1)[1] for line in output.splitlines() if label in line))


def _assert_dispatch(world, tool, name, model):
    result = _run(world, tool, name, "--model", model)
    assert result.returncode == 0, result.stdout + result.stderr
    kickoff = _reported(result.stdout, "kickoff file")
    workspace = _reported(result.stdout, "prepared directory")
    assert stat.S_IMODE(kickoff.stat().st_mode) == 0o600
    assert (workspace / "AGENTS.md").is_file()
    text = kickoff.read_text()
    source = (ROOT / "src/skills/plot-session/dispatcher.md").read_text()
    prefix = f"slopmeister-dispatcher={name} role=standing\n\n" if tool == "codex" else ""
    suffix = (
        f"\nThe invoking Slopmeister checkout is `{ROOT}`. Run Slopmeister commands with "
        f"`task --dir {ROOT}`, and resolve Slopmeister documentation paths against that "
        "checkout.\n"
    )
    assert text == prefix + source + suffix
    grants = json.loads((workspace / ".claude/access-settings.json").read_text())
    expected = {str(ROOT.resolve()), str(world.vault.resolve()), *temporary_roots(world)}
    assert set(grants["permissions"]["additionalDirectories"]) == expected
    assert f"'--model' '{model}'" in result.stdout
    assert "model_context_window" not in result.stdout
    assert "\033]6;1;bg;" not in result.stdout
    if tool == "claude":
        assert "--remote-control=dispatcher-claude-0" in result.stdout
        assert "'--permission-mode' 'auto'" in result.stdout
        assert not text.startswith("slopmeister-dispatcher=")
    else:
        assert "'--no-daemon'" in result.stdout
        assert "--add-dir" not in result.stdout
    assert codex_writable(workspace) == expected


@pytest.mark.parametrize("tool", ["claude", "codex"])
def test_public_dispatch_prepares_exact_kickoff_and_native_command(tmp_path, tool):
    """Bug: the Task port lost the role prompt, grants, model or tool-native arguments."""
    world = machine(tmp_path)
    models = ["fixture-model"] if tool == "claude" else ["gpt-5.6-sol", "gpt-6-astra"]
    for index, model in enumerate(models):
        _assert_dispatch(world, tool, f"dispatcher-{tool}-{index}", model)


@pytest.mark.parametrize("tool", ("claude", "codex"))
def test_dispatcher_command_marks_the_executed_client(tmp_path, monkeypatch, tool):
    """A fresh terminal must not start an agent on the unmarked desktop secret route."""
    client = tmp_path / ".local/bin" / tool
    client.parent.mkdir(parents=True)
    client.write_text(
        f"#!{sys.executable}\nimport os\n"
        "print('BROKER=' + os.environ.get('SLOPMEISTER_SECRET_BROKER', 'absent'))\n"
    )
    client.chmod(0o755)
    monkeypatch.setattr(command.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(command.shutil, "which", lambda name: str(client))
    monkeypatch.setattr(command, "sleep_guard", lambda: ())
    prefix = command.prefix(command.Settings(tool, "", ""), tmp_path)
    kickoff = tmp_path / "kickoff"
    kickoff.write_text("synthetic kickoff\n")
    env = {key: value for key, value in os.environ.items() if key != "SLOPMEISTER_SECRET_BROKER"}
    result = subprocess.run(
        ["/bin/sh", "-c", command.line(tmp_path, prefix, kickoff)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert result.stdout == "BROKER=1\n"


def test_codex_dispatch_preparation_pins_home_without_daemon(tmp_path):
    """Bug: the dispatcher needs a daemon or inherits a different Orca Codex home."""
    world = machine(tmp_path)
    result = _run(world, "codex", "phone", "--model", "gpt-6.1-sol")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "'--no-daemon'" in result.stdout
    assert f"'CODEX_HOME={world.codex}'" in result.stdout


def test_invalid_input_refuses_before_dispatch_state(tmp_path):
    """Bug: rejected model input still wrote a kickoff or prepared a session directory."""
    world = machine(tmp_path)
    result = _run(world, "claude", "phone", "--model", "-unsafe")
    assert result.returncode != 0 and "must not begin" in result.stderr
    assert not (world.root / "dispatch").exists()
    assert not list(world.sessions.glob("dispatcher-*"))


def test_traversal_dispatcher_name_is_refused_before_any_state(tmp_path):
    """Bug: a phone-supplied name with path traversal reaches the session directory or kickoff."""
    world = machine(tmp_path)
    result = _run(world, "claude", "../escape")
    assert result.returncode != 0 and "must match [a-z0-9][a-z0-9-]*" in result.stderr
    assert not (world.root / "dispatch").exists()
    assert not list(world.sessions.glob("dispatcher-*"))


def test_task_surface_keeps_dispatch_interactive():
    """Bug: routing dispatch through Python dropped Task's interactive terminal contract."""
    source = (ROOT / "taskfiles/session.yml").read_text()
    block = source.split("  dispatch:\n", 1)[1].split("\n  plot-session:\n", 1)[0]
    assert "interactive: true" in block
    assert "bin/slopmeister dispatch" in block


def test_exact_cross_tool_collision_refuses_but_neighbor_name_remains_free(tmp_path):
    """Bug: changing tools duplicated an exact phone name or blocked every neighboring name."""
    world = machine(tmp_path)
    marker = "slopmeister-dispatcher=collision-name role=standing"
    sleeper = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)", marker], env=os.environ
    )
    try:
        refused = _run(world, "claude", "collision-name")
        allowed = _run(world, "claude", "collision-name-2")
        assert refused.returncode != 0 and "already carries" in refused.stderr
        assert allowed.returncode == 0, allowed.stdout + allowed.stderr
    finally:
        sleeper.terminate()
        sleeper.wait(timeout=5)


@pytest.mark.parametrize(
    ("platform", "guard"),
    [
        ("linux", "'/usr/bin/systemd-inhibit' '--what=idle' '--who=slopmeister'"),
        ("darwin", "'/usr/bin/caffeinate' '-i'"),
    ],
)
def test_dispatch_line_carries_the_sleep_guard_of_its_system(tmp_path, platform, guard):
    """Bug: the dispatcher on Linux asks for caffeinate, or starts with no sleep guard at all."""
    world = machine(tmp_path)
    for tool in ("claude", "codex"):
        result = _run(world, tool, f"guard-{tool}", SLOPMEISTER_PLATFORM=platform)
        assert result.returncode == 0, result.stdout + result.stderr
        assert guard in result.stdout
        assert ("caffeinate" in result.stdout) == (platform == "darwin")
