"""The command file hands the native tool exactly the argv the launch asked for, through zsh."""

import json
from pathlib import Path
import re
import subprocess

import pytest

from slopmeister import paths
from slopmeister.launch.command import CODEX_SANDBOX
from tests.integration.launch.helpers import (
    KICKOFF,
    Machine,
    executable,
    launch,
    machine,
    reported,
    target,
)

# Both tool cases use one process-visible session name. Keep them on the same worker.
pytestmark = pytest.mark.xdist_group("launch-command-shell")

MODEL = "future model's $(touch SHOULD-NOT-EXIST); `false` $HOME"
RECORDER = (
    "#!/usr/bin/env python3\nimport json, os, sys\n"
    "open(os.environ['MODEL_ARGS'], 'w').write(json.dumps(sys.argv[1:]))\n"
)


def _claude(world: Machine, worktree: Path, recorded: list[str]) -> tuple[list[str], list[str]]:
    """The argv around the model and extra arguments; the session id is fresh per launch."""
    assert re.fullmatch(r"[a-f0-9-]{36}", recorded[4])
    before = [
        *(
            "--remote-control=example-client-argv-shell",
            "-n",
            "example-client-argv-shell",
            "--session-id",
            recorded[4],
        ),
        *("--strict-mcp-config", "--append-system-prompt-file", f"{worktree}/CLAUDE.md"),
        *("--setting-sources", "user,project"),
        *("--settings", f"{worktree}/.claude/access-settings.json"),
    ]
    return before, ["--permission-mode", "auto", "--", KICKOFF]


def _codex(world: Machine, worktree: Path, recorded: list[str]) -> tuple[list[str], list[str]]:
    after = [
        *("-c", 'project_root_markers=["AGENTS.md"]', "-c", "project_doc_fallback_filenames=[]"),
        *("-C", str(worktree), "--", f"{worktree.name}\n\n{KICKOFF}"),
    ]
    sandbox = CODEX_SANDBOX[paths.platform()].strip().split(" ", 1)
    return [
        "--no-daemon",
        "-c",
        'approval_policy="on-request"',
        "-c",
        'approvals_reviewer="auto_review"',
        sandbox[0],
        sandbox[1].strip("'"),
    ], after


def _assert_supported_models(world, repo, record, native):
    for index, model in enumerate(("gpt-5.6-sol", "gpt-6-astra")):
        name = f"example-client-context-{index}"
        result = launch(
            world, str(repo), "example-client", name, "--tool", "codex", "--model", model
        )
        command = reported(result.stdout, "command file")
        subprocess.run(
            ["zsh", "-f", command], env={**world.env, "MODEL_ARGS": str(record)}, check=True
        )
        supported = json.loads(record.read_text())
        before, after = native(world, repo / f".worktrees/{name}", supported)
        assert supported == [*before, "--model", model, *after]
        assert "model_context_window" not in supported


@pytest.mark.parametrize(
    ("tool", "binary", "extra", "native"),
    [
        (
            "claude",
            "bin/claude",
            ["--effort", "high"],
            _claude,
        ),
        ("codex", "home/.local/bin/codex", ["--config", 'notice="--model x"'], _codex),
    ],
)
def test_command_file_preserves_argv(tmp_path, tool, binary, extra, native):
    """Bug: zsh expands a quote, substitution or backtick in the model or a tool argument, or the
    argv is reordered so a variadic option swallows the kickoff."""
    world = machine(tmp_path)
    repo = target(tmp_path / "repo")
    executable(tmp_path / binary, RECORDER)
    result = launch(
        world,
        str(repo),
        "example-client",
        "example-client-argv-shell",
        "--tool",
        tool,
        "--model",
        MODEL,
        "--",
        *extra,
    )
    assert "model requested (prepared): " in result.stdout
    assert "model observed" not in result.stdout
    record = tmp_path / "argv.json"
    command = reported(result.stdout, "command file")
    subprocess.run(["zsh", "-f", command], env={**world.env, "MODEL_ARGS": str(record)}, check=True)
    recorded = json.loads(record.read_text())
    before, after = native(world, repo / ".worktrees/example-client-argv-shell", recorded)
    assert recorded == [*before, "--model", MODEL, *extra, *after]
    assert "model_context_window" not in recorded
    if tool == "codex":
        _assert_supported_models(world, repo, record, native)
