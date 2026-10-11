"""Migrated cross-tool review regressions."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from slopmeister.review.prompt import ReviewTarget
import slopmeister.review.run as review_run
from slopmeister.review.run import (
    run_review,
)
from slopmeister.review.schema import (
    CrossToolReviewError,
    ReviewDirection,
)
from tests.support.review_helpers import (
    CLEAN_REVIEW_JSON,
    VALID_REVIEW_JSON,
    FakeReviewRuntime,
    env_with_scrubbed_api_keys,
)


def test_run_review_never_calls_live_model_in_tests():
    fake = FakeReviewRuntime()
    fake.set_review_output(CLEAN_REVIEW_JSON)
    run_review(
        ReviewDirection.CODEX_TO_CLAUDE,
        ReviewTarget(prompt="Review.", cwd="."),
        runner=fake,
        env={"OPENAI_API_KEY": "sk-openai-test-key-1234567890abcdef"},
    )
    review_commands = [cmd for cmd in fake.commands if cmd[0] in {"codex", "claude"}]
    assert review_commands == fake.commands
    assert review_commands[0][0] == "claude"
    assert "OPENAI_API_KEY" not in fake.envs[0]
    assert "ANTHROPIC_API_KEY" not in fake.envs[0]


@pytest.mark.parametrize("direction", list(ReviewDirection))
def test_all_review_children_receive_exact_seven_key_projection(direction: ReviewDirection):
    fake = FakeReviewRuntime()
    parent, expected = env_with_scrubbed_api_keys()
    run_review(
        direction,
        ReviewTarget(prompt="Review named paths.", cwd="."),
        runner=fake,
        env={**parent, "CROSS_TOOL_REVIEW_TIMEOUT_SECONDS": "17"},
    )

    assert fake.envs == [expected]


def test_reviewer_nonzero_is_control_failure():
    fake = FakeReviewRuntime()
    fake.set_review_output("", stderr="auth failed", returncode=1)

    with pytest.raises(CrossToolReviewError) as raised:
        run_review(
            ReviewDirection.CODEX_TO_CLAUDE,
            ReviewTarget(prompt="Review.", cwd="."),
            runner=fake,
            env={},
        )

    assert raised.value.category.value == "CONTROL_FAILURE"


@pytest.mark.parametrize(
    "stdout,category",
    [
        ('{"permission_denials":[]}', "EXECUTION_FAILURE"),
        ('{"permission_denials":[{"tool":"Bash"}]}', "CONTROL_FAILURE"),
        ("truncated output: permission denied while reading", "CONTROL_FAILURE"),
        ('{"findings": [', "EXECUTION_FAILURE"),
    ],
)
def test_nonzero_requires_actual_permission_denial_evidence(stdout, category):
    fake = FakeReviewRuntime()
    fake.set_review_output(stdout, returncode=1)

    with pytest.raises(CrossToolReviewError) as raised:
        run_review(
            ReviewDirection.CODEX_TO_CLAUDE,
            ReviewTarget(prompt="Review.", cwd="."),
            runner=fake,
            env={},
        )

    assert raised.value.category.value == category
    assert raised.value.raw_stdout == stdout


@pytest.mark.parametrize(
    "direction, terminal, expected_state",
    [
        (ReviewDirection.CODEX_TO_CLAUDE, ("before", False), "unchanged"),
        (ReviewDirection.CODEX_TO_CLAUDE, ("after", False), "changed"),
        (ReviewDirection.CODEX_TO_CLAUDE, CrossToolReviewError("fatal"), "unverified"),
        (ReviewDirection.CLAUDE_TO_CODEX, ("before", False), "unchanged"),
    ],
)
def test_timeout_stays_primary_and_records_one_terminal_git_assessment(
    direction: ReviewDirection, terminal, expected_state: str, monkeypatch
):
    fake = FakeReviewRuntime()
    fake.worktrees = [("before", False), terminal]
    monkeypatch.setattr(review_run, "_worktree", fake.worktree)
    fake.set_review_exception(subprocess.TimeoutExpired(cmd=["claude"], timeout=600))

    with pytest.raises(CrossToolReviewError) as raised:
        run_review(
            direction,
            ReviewTarget(prompt="Review.", cwd="."),
            runner=fake,
            env={},
        )

    assert raised.value.category.value == "TIMEOUT"
    assert raised.value.mutation_state == expected_state
    assert [command[0] for command in fake.commands].count(direction.value.split("-")[-1]) == 1
    assert not fake.worktrees
    if direction == ReviewDirection.CLAUDE_TO_CODEX:
        codex_command = next(command for command in fake.commands if command[0] == "codex")
        schema_path = Path(codex_command[codex_command.index("--output-schema") + 1])
        assert not schema_path.exists()


@pytest.mark.parametrize(
    "envelope",
    [
        {"type": "result", "is_error": True, "result": '{"findings":[]}'},
        {"type": "result", "is_error": False},
        {"type": "result", "is_error": False, "result": 42},
    ],
)
def test_claude_error_or_invalid_envelope_is_invalid_reviewer_json(envelope: dict[str, object]):
    fake = FakeReviewRuntime()
    fake.set_review_output(json.dumps(envelope))

    with pytest.raises(CrossToolReviewError) as raised:
        run_review(
            ReviewDirection.CODEX_TO_CLAUDE,
            ReviewTarget(prompt="Review.", cwd="."),
            runner=fake,
            env={},
        )

    assert raised.value.category.value == "INVALID_REVIEWER_JSON"


def test_codex_to_claude_streams_large_prompt_over_stdin_not_argv():
    fake = FakeReviewRuntime()
    large_marker = "review-payload-marker-" * 2_000
    run_review(
        ReviewDirection.CODEX_TO_CLAUDE,
        ReviewTarget(prompt=large_marker, cwd="."),
        runner=fake,
        env={},
    )

    claude_command = next(command for command in fake.commands if command[0] == "claude")
    assert not any(large_marker in part for part in claude_command)
    assert fake.stdin_texts[0] is not None
    assert large_marker in fake.stdin_texts[0]


def test_run_review_normalizes_claude_json_envelope_stdout():
    fake = FakeReviewRuntime()
    fake.set_review_output(
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": VALID_REVIEW_JSON,
            }
        )
    )
    result = run_review(
        ReviewDirection.CODEX_TO_CLAUDE,
        ReviewTarget(prompt="Review.", cwd="."),
        runner=fake,
        env={},
    )
    assert result.findings[0].title == "Missing guard"


@pytest.mark.parametrize(
    "result_text",
    [
        f"```json\n{VALID_REVIEW_JSON}\n```",
        f"Here is the review:\n```json\n{VALID_REVIEW_JSON}\n```",
        f"Review result follows.\n{VALID_REVIEW_JSON}\nEnd.",
    ],
)
def test_run_review_extracts_json_after_claude_envelope_unwrap(result_text: str):
    fake = FakeReviewRuntime()
    fake.set_review_output(
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": result_text,
            }
        )
    )
    result = run_review(
        ReviewDirection.CODEX_TO_CLAUDE,
        ReviewTarget(prompt="Review.", cwd="."),
        runner=fake,
        env={},
    )
    assert result.findings[0].title == "Missing guard"
