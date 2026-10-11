"""The op a session runs reads op run lines like the real command and refuses value printing."""

import os

import pytest

from slopmeister.session import secret_run
from tests.support.op_session import env_file

EXECVE, EXECVPE = os.execve, os.execvpe
pytestmark = pytest.mark.usefixtures("session")


@pytest.mark.parametrize(
    "args,files,command",
    [
        (["--env-file=a.env", "--", "true"], ["a.env"], ["true"]),
        (
            ["--env-file", "a.env", "--env-file=b.env", "--", "sh", "-c", "x"],
            ["a.env", "b.env"],
            ["sh", "-c", "x"],
        ),
        (["--", "printenv", "--", "X"], [], ["printenv", "--", "X"]),
    ],
)
def test_op_run_line_is_read_like_the_real_command(args, files, command):
    """Bug: a project target's env file flag or its command tail is misread."""
    assert secret_run.parse(args) == (files, command)


@pytest.mark.parametrize(
    "args",
    [["--no-masking", "--", "true"], ["--account", "x", "--", "true"], ["--env-file=a"], ["true"]],
)
def test_unsupported_or_unmasked_lines_are_refused(args):
    """Bug: a flag that prints values or changes the account is silently passed on."""
    with pytest.raises(ValueError):
        secret_run.parse(args)


@pytest.mark.parametrize("line", ['TEXT="value"garbage', "TEXT"])
def test_malformed_lines_refuse_before_the_command_runs(tmp_path, line, capsys):
    """Bug: a typo in an env file runs the command with a misread environment or a traceback."""
    (tmp_path / "x.env").write_text(line + "\n")
    code = secret_run.main(["run", "--env-file", str(tmp_path / "x.env"), "--", "/bin/echo", "RAN"])
    out, err = capsys.readouterr()
    assert code == 1 and "RAN" not in out and err.startswith("op run:")


@pytest.mark.parametrize("text", ['X=" op://Production/Item/field"\n', "KEEP=1\n"])
def test_padded_reference_is_refused_as_the_real_op_would_resolve_it(
    tmp_path, monkeypatch, capsys, session, text
):
    """Bug: the real op trims and resolves a value that the tier decision read as a literal."""
    if text.startswith("KEEP"):
        monkeypatch.setenv("PADDED", "\top://Production/Item/field ")
    assert secret_run.main(env_file(tmp_path, text)) == 1
    assert "is not a secret reference" in capsys.readouterr().err
    assert session == []


def test_reference_inside_a_longer_value_stays_a_literal(tmp_path, session):
    """Bug: a URL or a note that merely contains op:// blocks every op run."""
    text = "URL=postgres://user:op://Everyday/Db/password@host\nDEMO=op://Everyday/I/f\n"
    assert secret_run.main(env_file(tmp_path, text)) is None
    assert session[0][1]["URL"] == "postgres://user:op://Everyday/Db/password@host"


@pytest.mark.parametrize(
    "args",
    [
        ["read", "op://A/B/C"],
        ["inject"],
        ["item", "get", "X"],
        ["items", "get", "X"],
        ["item", "share", "X"],
        ["items", "share", "X"],
        ["--account", "example", "items", "share", "X"],
        ["document", "get", "X"],
        ["documents", "get", "X"],
        ["--format=json", "read", "op://A/B/C"],
        ["item", "--format=json", "get", "X"],
        ["--account", "example", "run", "--", "true"],
    ],
)
def test_value_printing_commands_are_refused_whatever_flags_surround_them(args, capsys, session):
    """Bug: an agent prints a secret through a plural spelling or behind a global flag."""
    assert secret_run.main(args) == 1
    assert "is refused for agents" in capsys.readouterr().err
    assert session == []


def test_other_subcommands_pass_to_the_real_op(tmp_path, monkeypatch, session):
    """Bug: op --version or op whoami stop working, or the launcher calls itself forever."""
    own = tmp_path / "bin"
    own.mkdir()
    (own / "op").write_text("#!/bin/sh\n")
    (own / "op").chmod(0o755)
    monkeypatch.setenv("PATH", f"{own}{os.pathsep}{tmp_path / 'real'}")
    monkeypatch.setattr("sys.argv", [str(own / "op")])
    secret_run.main(["--version"])
    assert [argv for argv, _ in session] == [[str(tmp_path / "real/op"), "--version"]]


def test_unmarked_session_is_the_real_op(monkeypatch, session):
    """Bug: the operator's own terminal gets tiers and refusals, or op signin stops working."""
    monkeypatch.delenv(secret_run.MARK)
    secret_run.main(["read", "op://A/B/C"])
    secret_run.main(["run", "--no-masking", "--", "true"])
    secret_run.main(["item", "share", "X"])
    assert [argv[1:] for argv, _ in session] == [
        ["read", "op://A/B/C"],
        ["run", "--no-masking", "--", "true"],
        ["item", "share", "X"],
    ]


def test_missing_real_op_is_named(tmp_path, monkeypatch, capsys):
    """Bug: a pass-through on a machine without op fails with a traceback."""
    monkeypatch.setenv("PATH", str(tmp_path / "nothing-here"))
    assert secret_run.main(["--version"]) == 127
    assert "not installed" in capsys.readouterr().err


def test_session_is_the_containing_repository(tmp_path):
    """Bug: the operator sees a subdirectory name instead of the session's workspace name."""
    repo = tmp_path / "example-app-123-example"
    (repo / ".git").mkdir(parents=True)
    nested = repo / "services" / "web"
    nested.mkdir(parents=True)
    assert secret_run.session_name(nested) == "example-app-123-example"
    assert secret_run.session_name(tmp_path / "loose") == "loose"


def test_value_the_system_cannot_pass_is_reported_not_raised(tmp_path, monkeypatch, capsys):
    """Bug: a null byte in an env file ends op run with a traceback."""
    # Only the two exec calls are real again. The session stays marked, so nothing real starts.
    monkeypatch.setattr(os, "execve", EXECVE)
    monkeypatch.setattr(os, "execvpe", EXECVPE)
    (tmp_path / "x.env").write_text("TEXT=a\x00b\n")
    code = secret_run.main(["run", "--env-file", str(tmp_path / "x.env"), "--", "/bin/echo", "RAN"])
    assert code == 127 and capsys.readouterr().err.startswith("op: /bin/echo:")
