"""A timed-out reviewer leaves the redacted tail of its stderr on the error."""

import pytest

from slopmeister.review.process import STDERR_LINE_CHARS, STDERR_TAIL_LINES
from slopmeister.review.prompt import ReviewTarget
from slopmeister.review.run import owned_reviewer_runner, run_review
from slopmeister.review.schema import CrossToolReviewError, ReviewDirection
from tests.support.fakes import fake_binary
from tests.support.review_helpers import FakeReviewRuntime

FLAG_VALUE = "abcdefghijklmnopqrstuvwx"
PLAIN_SECRET = "sk-" + "abcdefghijklmnop1234"


def _stderr_lines() -> list[str]:
    lines = [f"line {number}" for number in range(1, 31)]
    lines[9] = "--token"
    lines[10] = f"{FLAG_VALUE} line 11"
    lines[19] = f"key {PLAIN_SECRET} line 20"
    lines[24] = "\x1b[31mred\x1b[0m line 25"
    lines[27] = "x" * 1000
    return lines


def _timed_out(tmp_path, monkeypatch, script: str) -> CrossToolReviewError:
    tool = fake_binary(tmp_path, "codex", script)
    monkeypatch.setenv("CROSS_TOOL_REVIEW_TIMEOUT_SECONDS", "2")
    with pytest.raises(CrossToolReviewError) as raised:
        owned_reviewer_runner([str(tool)])
    assert raised.value.category.value == "TIMEOUT"
    return raised.value


@pytest.mark.xdist_group("review-process-tree")
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_timeout_keeps_the_redacted_bounded_stderr_tail(tmp_path, monkeypatch, newline):
    """Escaping bugs: stderr dropped at the timeout, the bound ignored, a secret split
    by the cut or a terminal code printed, one line of any length."""
    written = tmp_path / "stderr.txt"
    written.write_bytes((newline.join(_stderr_lines()) + newline).encode())
    error = _timed_out(tmp_path, monkeypatch, f'cat "{written}" >&2\nsleep 30')
    tail = error.stderr_tail

    assert len(tail) == STDERR_TAIL_LINES
    assert tail[-1] == "line 30" and "line 9" not in tail
    assert tail[0] == "[REDACTED] line 11"
    assert FLAG_VALUE not in "".join(tail) and PLAIN_SECRET not in "".join(tail)
    assert "key [REDACTED] line 20" in tail
    assert all(ord(char) >= 32 and ord(char) != 127 for line in tail for char in line)
    assert "x" * STDERR_LINE_CHARS in tail
    assert max(len(line) for line in tail) == STDERR_LINE_CHARS


@pytest.mark.xdist_group("review-process-tree")
def test_timeout_of_a_silent_reviewer_reports_an_empty_tail(tmp_path, monkeypatch):
    """Escaping bug: silence is indistinguishable from the tail not being collected."""
    assert _timed_out(tmp_path, monkeypatch, "sleep 30").stderr_tail == ()


def test_run_review_keeps_the_stderr_tail_on_the_timeout_it_raises():
    """Escaping bug: the timeout rebuilt with its mutation assessment lost the tail."""
    fake = FakeReviewRuntime()
    fake.set_review_exception(
        CrossToolReviewError("reviewer timed out", category="TIMEOUT", stderr_tail=("last",))
    )
    with pytest.raises(CrossToolReviewError) as raised:
        run_review(
            ReviewDirection.CLAUDE_TO_CODEX,
            ReviewTarget(prompt="Review.", cwd="."),
            runner=fake,
            env={},
        )
    assert raised.value.mutation_state == "unchanged"
    assert raised.value.stderr_tail == ("last",)
