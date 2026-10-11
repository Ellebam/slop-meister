"""Bounded failed-check evidence stays correct."""

from pathlib import Path

from slopmeister.check import results
from tests.support.trees import write


def failed_result(log: Path) -> dict:
    return {
        "results": [
            {
                "id": "fixture-failure",
                "returncode": 1,
                "elapsed_seconds": 1.0,
                "log": str(log),
            }
        ]
    }


def test_terminal_failure_keeps_the_concise_log_path(tmp_path: Path) -> None:
    log = write(tmp_path, "failed.log", "FAILED hidden\n")
    lines = results.console_lines(failed_result(log), terminal=True)
    assert lines == ["FAIL fixture-failure 1.0s", f"  log: {log}"]


def test_non_terminal_failure_prints_the_short_log(tmp_path: Path) -> None:
    log = tmp_path / "failed.log"
    log.write_bytes(b"bad byte: \xff\nFAILED tests/test_widget.py::test_broken\n")
    output = "\n".join(results.console_lines(failed_result(log), terminal=False))
    assert "  | bad byte: \ufffd" in output
    assert "  | FAILED tests/test_widget.py::test_broken" in output
    assert "truncated" not in output


def test_failure_excerpt_enforces_line_and_byte_bounds(tmp_path: Path) -> None:
    log = write(tmp_path, "lines.log", "".join(f"line-{index}\n" for index in range(101)))
    output = results.console_lines(failed_result(log), terminal=False)
    assert "  | line-0" not in output and "  | line-100" in output
    assert any("truncated" in line for line in output)
    log.write_bytes(b"x" * (results.FAILURE_BYTES + 1) + b"\nFAILED final\n")
    output = results.console_lines(failed_result(log), terminal=False)
    payload = [line.removeprefix("  | ") for line in output if line.startswith("  | ")]
    assert "FAILED final" in payload and len("\n".join(payload).encode()) <= results.FAILURE_BYTES
    log.write_bytes(b"\xff" * results.FAILURE_BYTES)
    output = results.console_lines(failed_result(log), terminal=False)
    payload = [line.removeprefix("  | ") for line in output if line.startswith("  | ")]
    assert len("\n".join(payload).encode()) <= results.FAILURE_BYTES


def test_failure_excerpt_neutralizes_workflow_commands(tmp_path: Path) -> None:
    log = tmp_path / "commands.log"
    log.write_bytes(b"ok\r::add-mask::secret\n\t::warning::fake\ntext ##[error]fake\n")
    output = results.console_lines(failed_result(log), terminal=False)
    excerpt = [line for line in output if line.startswith("  | ")]
    assert len(excerpt) == 4 and all(line.lstrip().startswith("|") for line in excerpt)
    assert not any("##[" in line for line in excerpt)
    assert any("text ## [error]fake" in line for line in excerpt)
