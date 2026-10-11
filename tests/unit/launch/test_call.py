"""In-process package commands stop the launch exactly as their child processes did."""

import pytest

from slopmeister.launch import cli
from slopmeister.launch.model import Launch, Stop, call


def _returns(code):
    def main(argv):
        print("value")
        return code

    return main


def _exits(value):
    def main(argv):
        raise SystemExit(value)

    return main


def test_captured_value_is_returned_without_trailing_newline():
    assert call(_returns(0), [], capture=True) == "value"


@pytest.mark.parametrize(
    ("main", "code", "stderr"),
    [(_returns(1), 1, ""), (_exits(2), 2, ""), (_exits("refused: reason"), 1, "refused: reason\n")],
)
def test_in_process_failure_stops_launch(main, code, stderr, capsys):
    """Bug: a failed claim or install step returns 1 or exits and the launcher carries on."""
    with pytest.raises(Stop) as stopped:
        call(main, [], capture=True)
    assert stopped.value.code == code
    assert capsys.readouterr().err == stderr


def test_unexpected_failure_after_open_reports_that_a_worker_may_be_live(monkeypatch, capsys):
    """Bug: an exception after opening rolled back resources beneath a possible worker."""
    launch = Launch("scratch", "scratch-one", "/repo")

    def fail(current, prepared):
        current.open_attempted = True
        raise RuntimeError("after open")

    monkeypatch.setattr(cli, "_validate", lambda argv, worktree_file: launch)
    monkeypatch.setattr(cli, "_launch", fail)
    assert cli.run([]) == (1, True)
    assert "RuntimeError: after open" in capsys.readouterr().err
    launch.open_attempted = False
    monkeypatch.setattr(
        cli, "_launch", lambda current, prepared: (_ for _ in ()).throw(RuntimeError("before open"))
    )
    with pytest.raises(RuntimeError, match="before open"):
        cli.run([])
