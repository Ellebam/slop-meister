"""An OpenCode worker starts with Slopmeister's instructions, deny rules and the exact kickoff."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.integration.launch.helpers import (
    Machine,
    executable,
    launch,
    machine,
    reported,
    target,
)

RECORDER = (
    "#!/usr/bin/env python3\nimport json, os, sys\n"
    "keys = ('OPENCODE_DISABLE_CLAUDE_CODE', 'OPENCODE_CONFIG_CONTENT')\n"
    "record = {'argv': sys.argv[1:], 'env': {k: os.environ.get(k) for k in keys}}\n"
    "open(os.environ['MODEL_ARGS'], 'w').write(json.dumps(record))\n"
)


def _world(tmp_path: Path) -> tuple[Machine, Path]:
    world = machine(tmp_path)
    (tmp_path / "plots/example-client/plot.toml").write_text(
        '[plot]\nbase = "code"\n[target]\ntasks = "manual"\n'
        '[target.repository]\ncommit = "allow"\nshipping = "allow"\n[slots]\nnone = true\n'
    )
    executable(tmp_path / "bin/opencode", RECORDER)
    return world, target(tmp_path / "repo")


@pytest.mark.parametrize(
    ("permission", "replacement"),
    [("commit", 'commit = "deny"'), ("shipping", 'shipping = "deny"'), ("shipping", "")],
    ids=["denied-commit", "denied-shipping", "omitted-shipping"],
)
@pytest.mark.parametrize("directory", [False, True])
def test_denied_plot_permission_refuses_opencode_before_preparation(
    tmp_path, permission, replacement, directory
):
    """Bug: OpenCode bypasses the plot's denied Git policy, including a directory launch."""
    world, repo = _world(tmp_path)
    plot = tmp_path / "plots/example-client/plot.toml"
    plot.write_text(plot.read_text().replace(f'{permission} = "allow"', replacement))
    args = (
        ("example-client", "example-client-oc", "--directory")
        if directory
        else (str(repo), "example-client", "example-client-oc")
    )
    result = launch(world, *args, "--tool", "opencode", ok=False)
    assert f"{permission} permission is deny" in result.stderr
    assert "docs/opencode.md" in result.stderr
    assert not (repo / ".worktrees").exists()
    assert not world.state.exists() and not world.sessions.exists()


def test_command_file_starts_opencode_with_owned_configuration(tmp_path):
    """Bug: OpenCode starts with the operator's Claude skills, without the permission rules,
    with --auto, or with a kickoff zsh mangled."""
    world, repo = _world(tmp_path)
    kickoff = 'Mode: freeform\n\nIt\'s "quoted" $(touch SHOULD-NOT-EXIST) `false` $HOME'
    args = ("--tool", "opencode", "--model", "p/m")
    result = launch(world, str(repo), "example-client", "example-client-oc", *args, kickoff=kickoff)
    record = tmp_path / "argv.json"
    command = reported(result.stdout, "command file")
    subprocess.run(["zsh", "-f", command], env={**world.env, "MODEL_ARGS": str(record)}, check=True)
    recorded = json.loads(record.read_text())
    worktree = repo / ".worktrees/example-client-oc"
    assert recorded["argv"] == [str(worktree), "-m", "p/m", "--prompt", kickoff]
    assert not list(tmp_path.rglob("SHOULD-NOT-EXIST"))
    assert recorded["env"]["OPENCODE_DISABLE_CLAUDE_CODE"] == "1"
    rules = json.loads(recorded["env"]["OPENCODE_CONFIG_CONTENT"])["permission"]["bash"]
    assert rules["op read *"] == "deny"
    # Bug: the tester silently gains merge rights when needs_intent renders as allow.
    assert rules["gh pr merge"] == rules["gh pr merge *"] == "ask"
    assert rules["gh pr view *"] == "allow"
    permission = json.loads(recorded["env"]["OPENCODE_CONFIG_CONTENT"])["permission"]
    assert permission["external_directory"] == {f"{world.vault}/*": "allow"}
    assert "--auto" not in Path(command).read_text()


def test_extra_tool_arguments_are_refused(tmp_path):
    """Bug: `-- --auto` or `-- --session <id>` weakens permissions or swaps the session."""
    world, repo = _world(tmp_path)
    for extra in (["--auto"], ["--session", "ses_x"], ["--prompt", "other"]):
        result = launch(
            world,
            str(repo),
            "example-client",
            "example-client-oc",
            "--tool",
            "opencode",
            "--",
            *extra,
            ok=False,
        )
        assert "would override Slopmeister-owned configuration: " + extra[0] in result.stderr


def test_redispatch_is_refused_until_supported(tmp_path):
    world, repo = _world(tmp_path)
    result = launch(
        world,
        str(repo),
        "example-client",
        "example-client-oc",
        "--redispatch",
        "--tool",
        "opencode",
        ok=False,
    )
    assert "not supported for OpenCode yet" in result.stderr


def test_missing_provider_variable_refuses_before_anything_starts(tmp_path):
    """Bug: the worker opens without its key and the provider answers with an opaque error page."""
    world, repo = _world(tmp_path)
    # A CI runner sets XDG_CONFIG_HOME, and OpenCode reads its configuration from there.
    home = Path(world.env["HOME"]) / ".config"
    config = home / "opencode/opencode.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"provider":{"p":{"options":{"apiKey":"{env:FAKE_PROVIDER_KEY}"}}}}')
    xdg = {"XDG_CONFIG_HOME": str(home)}
    args = (str(repo), "example-client", "example-client-oc", "--tool", "opencode")
    result = launch(world, *args, ok=False, **xdg)
    assert "provider variable FAKE_PROVIDER_KEY unset" in result.stderr
    assert not (repo / ".worktrees/example-client-oc").exists()
    launch(world, *args, FAKE_PROVIDER_KEY="set", **xdg)


def test_missing_binary_refuses(tmp_path):
    world, repo = _world(tmp_path)
    (tmp_path / "bin/opencode").unlink()
    # Homebrew keeps python3 beside opencode, so the interpreter is linked in on its own.
    (tmp_path / "python").mkdir()
    (tmp_path / "python/python3").symlink_to(sys.executable)
    kept = [
        entry
        for entry in world.env["PATH"].split(os.pathsep)
        if not (Path(entry) / "opencode").exists()
    ]
    path = os.pathsep.join([str(tmp_path / "python"), *kept])
    result = launch(
        world,
        str(repo),
        "example-client",
        "example-client-oc",
        "--tool",
        "opencode",
        ok=False,
        PATH=path,
    )
    assert "opencode not found" in result.stderr
