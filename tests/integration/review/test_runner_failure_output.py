"""Migrated cross-tool review regressions."""

from __future__ import annotations

import json

import pytest

from slopmeister.review.prompt import ReviewTarget
from slopmeister.review.run import (
    run_review,
)
from slopmeister.review.schema import (
    CrossToolReviewError,
    ReviewDirection,
)
from tests.support.review_helpers import (
    FakeReviewRuntime,
)


@pytest.mark.parametrize(
    "result_text, match",
    [
        ("No JSON here.", "does not contain"),
        ('{"findings":[]}\n{"findings":[]}', "multiple JSON objects"),
        ('```json\n{"findings":[]}\n```\n```json\n{"findings":[]}\n```', "multiple JSON blocks"),
    ],
)
def test_run_review_rejects_missing_or_ambiguous_claude_json(result_text: str, match: str):
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
    with pytest.raises(CrossToolReviewError, match=match):
        run_review(
            ReviewDirection.CODEX_TO_CLAUDE,
            ReviewTarget(prompt="Review.", cwd="."),
            runner=fake,
            env={},
        )


def test_nonzero_native_stream_json_permission_denial_is_control_failure():
    """Escaping bug: native JSONL denials were treated as retryable command failures."""
    fake = FakeReviewRuntime()
    fake.set_review_output(
        "\n".join(
            json.dumps(event)
            for event in (
                {"type": "system", "subtype": "init", "session_id": "session-211"},
                {
                    "type": "result",
                    "is_error": True,
                    "permission_denials": [{"tool_name": "Bash"}],
                },
            )
        ),
        returncode=1,
    )

    with pytest.raises(CrossToolReviewError) as raised:
        run_review(
            ReviewDirection.CODEX_TO_CLAUDE,
            ReviewTarget(prompt="Review.", cwd="."),
            runner=fake,
            env={},
        )

    assert raised.value.category.value == "CONTROL_FAILURE"


def test_nonzero_permission_denial_json_with_stderr_is_control_failure():
    """Escaping bug: adjacent stderr prevented parsing valid denial JSON."""
    fake = FakeReviewRuntime()
    fake.set_review_output(
        '{"permission_denials":[{"tool":"Bash"}]}',
        stderr="warning: startup note",
        returncode=1,
    )

    with pytest.raises(CrossToolReviewError) as raised:
        run_review(
            ReviewDirection.CODEX_TO_CLAUDE,
            ReviewTarget(prompt="Review.", cwd="."),
            runner=fake,
            env={},
        )

    assert raised.value.category.value == "CONTROL_FAILURE"


def test_nonzero_stdout_is_redacted_and_persisted():
    fake = FakeReviewRuntime()
    fake.set_review_output(
        "partial output ANTHROPIC_API_KEY=sk-ant-api03-12345678901234567890 then crash",
        returncode=1,
    )

    with pytest.raises(CrossToolReviewError) as raised:
        run_review(
            ReviewDirection.CODEX_TO_CLAUDE,
            ReviewTarget(prompt="Review.", cwd="."),
            runner=fake,
            env={},
        )

    assert raised.value.raw_stdout == "partial output ANTHROPIC_API_KEY=[REDACTED] then crash"
