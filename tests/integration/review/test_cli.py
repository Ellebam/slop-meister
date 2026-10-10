"""The small review CLI exposes only execution, replay and exact replacement."""

import json
import uuid

import pytest

from slopmeister.review import cli
from slopmeister.review.config import ReviewerConfig
from slopmeister.review.schema import CrossToolReviewError, ReviewResult, SecurityLens
from slopmeister.session import launch_identity
from tests.support.repos import scratch_repo
from tests.support.review_helpers import DEFAULTS

CLEAN = ReviewResult((), SecurityLens(None, ("secrets",), "Nothing found."))


def _ready(monkeypatch, tmp_path, tool="codex"):
    workspace = scratch_repo(tmp_path / "cli-task")
    monkeypatch.chdir(workspace)
    session = str(uuid.uuid4())
    monkeypatch.setenv("CODEX_THREAD_ID", session)
    path = launch_identity.path(workspace)
    path.parent.mkdir(mode=0o700, parents=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "state": "confirmed",
                "workspace": str(workspace),
                "task": workspace.name,
                "tool": tool,
                "session_id": session,
            }
        )
    )
    path.chmod(0o600)
    return workspace


def _args(workspace, *tail):
    return [
        "review",
        "--direction",
        "codex-to-claude",
        "--mode",
        "plan",
        "--cwd",
        str(workspace),
        "--prompt",
        "Review.",
        *tail,
    ]


def _read_dir_args(workspace, prompt, directories):
    args = [
        "review", "--direction", "codex-to-claude", "--mode", "diff",
        "--cwd", str(workspace), "--prompt-file", str(prompt),
    ]  # fmt: skip
    for directory in directories:
        args.extend(("--read-dir", str(directory)))
    return args


def test_model_and_effort_override_only_the_reviewer(monkeypatch, tmp_path):
    workspace = _ready(monkeypatch, tmp_path)
    seen = {}

    def run(direction, target, *, runner, config):
        seen.update(direction=direction, target=target, config=config)
        return CLEAN

    monkeypatch.setattr(cli, "run_review", run)
    assert cli.main(_args(workspace, "--model", "claude-big", "--effort", "xhigh")) == 0
    assert isinstance(seen["config"], ReviewerConfig)
    assert seen["config"].claude_model == "claude-big"
    assert seen["config"].claude_effort == "xhigh"


@pytest.mark.parametrize(
    "tail, expected",
    [
        (["--model", "claude-big"], ("claude-big", DEFAULTS["claude"]["effort"])),
        (["--effort", "xhigh"], (DEFAULTS["claude"]["model"], "xhigh")),
    ],
)
def test_single_axis_override_keeps_the_other_default(monkeypatch, tmp_path, tail, expected):
    """Escaping bug: a model-only or effort-only run silently drops the other committed default."""
    workspace = _ready(monkeypatch, tmp_path)
    seen = {}

    def run(direction, target, *, runner, config):
        seen["config"] = config
        return CLEAN

    monkeypatch.setattr(cli, "run_review", run)
    assert cli.main(_args(workspace, *tail)) == 0
    assert (seen["config"].claude_model, seen["config"].claude_effort) == expected


def test_help_has_no_caller_controlled_identity_or_collection(capsys):
    with pytest.raises(SystemExit) as raised:
        cli.main(["review", "--help"])
    assert raised.value.code == 0
    output = capsys.readouterr().out
    for removed in ("--task", "--name", "--origin-tool", "--origin-session", "collect"):
        assert removed not in output
    with pytest.raises(SystemExit) as raised:
        cli.main(["replace", "--help"])
    assert raised.value.code == 0
    assert "--mode" in capsys.readouterr().out


def test_review_has_no_built_in_fake_reviewer(monkeypatch, tmp_path, capsys):
    """Escaping bug: a flag that fabricates a clean gate ships in the product command."""
    workspace = _ready(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as raised:
        cli.main(_args(workspace, "--fixture-output", "clean"))
    assert raised.value.code == 2
    assert "unrecognized arguments: --fixture-output clean" in capsys.readouterr().err


def test_read_directories_and_prompt_file_reach_the_target(monkeypatch, tmp_path):
    workspace = _ready(monkeypatch, tmp_path)
    first, second = tmp_path / "one", tmp_path / "two with spaces"
    first.mkdir()
    second.mkdir()
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Inspect exact inputs.")
    seen = {}

    def run(direction, target, *, runner, config):
        seen["target"] = target
        return CLEAN

    monkeypatch.setattr(cli, "run_review", run)
    args = _read_dir_args(workspace, prompt, (first, second))
    assert cli.main(args) == 0
    assert seen["target"].prompt == "Inspect exact inputs."
    assert seen["target"].read_dirs == (str(first.resolve()), str(second.resolve()))


@pytest.mark.parametrize("fault", ["prepared", "prepared-with-session", "task-mismatch"])
def test_unconfirmed_or_tampered_launcher_identity_blocks_before_review(
    monkeypatch, tmp_path, fault
):
    workspace = _ready(monkeypatch, tmp_path)
    path = launch_identity.path(workspace)
    record = json.loads(path.read_text())
    if fault.startswith("prepared"):
        record["state"] = "prepared"
        if fault == "prepared":
            record.pop("session_id")
    else:
        record["task"] = "other-task"
    path.write_text(json.dumps(record))
    path.chmod(0o600)
    calls = []
    monkeypatch.setattr(cli, "run_review", lambda *a, **k: calls.append(a) or CLEAN)
    assert cli.main(_args(workspace)) == 1
    assert not calls


def test_repository_target_cannot_borrow_another_launcher_task(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    other = scratch_repo(tmp_path / "other")
    calls = []
    monkeypatch.setattr(cli, "run_review", lambda *a, **k: calls.append(a) or CLEAN)
    assert cli.main(_args(other)) == 1
    assert not calls
    assert not (other / ".git/slopmeister-config").exists()


@pytest.mark.parametrize(
    ("tail", "expected"),
    [
        (("first", "last"), ["stderr tail, last 2 lines", "stderr| first", "stderr| last"]),
        ((), ["stderr tail, empty"]),
    ],
)
def test_timeout_prints_the_stderr_tail_after_the_failure_line(
    monkeypatch, tmp_path, capsys, tail, expected
):
    """Escaping bug: the tail reached the error and was never shown to the launching agent."""
    workspace = _ready(monkeypatch, tmp_path)

    def timed_out(*_args, **_options):
        raise CrossToolReviewError("reviewer timed out", category="TIMEOUT", stderr_tail=tail)

    monkeypatch.setattr(cli, "run_review", timed_out)
    assert cli.main(_args(workspace)) == 1
    printed = capsys.readouterr()
    logged = [line.removeprefix("cross-tool-review: ") for line in printed.err.splitlines()]
    start = next(i for i, line in enumerate(logged) if line.startswith("failed category=TIMEOUT"))
    assert logged[start + 1 :] == expected
    assert "**Status:** BLOCKED" in printed.out and "stderr" not in printed.out
