"""The op a session runs reads op run lines like the real command and never prints a value."""

import os
from pathlib import Path

import pytest

from slopmeister.session import secret_run, secret_transport


@pytest.fixture(autouse=True)
def marked_session(monkeypatch, tmp_path):
    """Every test runs as a marked session with no real op reachable, exec is recorded."""
    monkeypatch.setenv(secret_run.MARK, "1")
    monkeypatch.setenv("PATH", str(tmp_path / "no-op-here"))
    monkeypatch.delenv(secret_run.LAUNCHER, raising=False)
    calls = []
    monkeypatch.setattr(os, "execv", lambda binary, argv: calls.append((binary, argv)))
    return calls


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
    """Bug: a example-app target's env file flag or its command tail is misread."""
    assert secret_run.parse(args) == (files, command)


@pytest.mark.parametrize(
    "args",
    [["--no-masking", "--", "true"], ["--account", "x", "--", "true"], ["--env-file=a"], ["true"]],
)
def test_unsupported_or_unmasked_lines_are_refused(args):
    """Bug: a flag that prints values or that the broker cannot honour is silently dropped."""
    with pytest.raises(ValueError):
        secret_run.parse(args)


def test_env_file_forms_and_precedence(tmp_path, monkeypatch):
    """Bug: comments, export prefixes, quotes, expansion or literals break a real env file."""
    first = tmp_path / "first.env"
    first.write_text(
        "# comment\n\nexport TOKEN=op://Example/Item/credential\n"
        "NOTE=op://Example/Item/note # inline comment\n"
        "PLAIN='literal value # kept'\nBASE=Example Vault/My Item\n"
        'HOST="op://${BASE}/hostname"\nUSER_HOME=$HOME/x\n'
    )
    second = tmp_path / "second.env"
    second.write_text("TOKEN=op://Example/Other/credential\n")
    monkeypatch.setenv("HOME", "/h")
    monkeypatch.setenv("SHELL_REF", "op://Example/Shell/field?ssh-format=openssh")
    monkeypatch.setenv("TOKEN", "op://Example/Shell/overridden")
    literals, references = secret_run.environment([str(first), str(second)])
    assert literals == {
        "PLAIN": "literal value # kept",
        "BASE": "Example Vault/My Item",
        "USER_HOME": "/h/x",
    }
    assert references == {
        "TOKEN": "op://Example/Other/credential",
        "NOTE": "op://Example/Item/note",
        "HOST": "op://Example Vault/My Item/hostname",
        "SHELL_REF": "op://Example/Shell/field?ssh-format=openssh",
    }


def test_empty_and_escaped_values_match_the_real_command(tmp_path):
    """Bug: EMPTY= crashes op run, and an escaped quote ends a value early, unlike the real op."""
    (tmp_path / "x.env").write_text(
        'EMPTY=\nTEXT="say \\"hello\\""\nSINGLE=\'a "b"\'\nKNOWN=k\nKEPT="\\$KNOWN and $KNOWN"\n'
    )
    literals, references = secret_run.environment([str(tmp_path / "x.env")])
    assert references == {}
    assert literals == {
        "EMPTY": "",
        "TEXT": 'say "hello"',
        "SINGLE": 'a "b"',
        "KNOWN": "k",
        "KEPT": "$KNOWN and k",
    }


def test_escapes_read_in_one_pass_like_the_real_command(tmp_path):
    """Bug: a doubled backslash stays doubled, so a command receives a different literal."""
    (tmp_path / "x.env").write_text('TEXT="a\\\\b \\"q\\" \\$x"\n')
    literals, _ = secret_run.environment([str(tmp_path / "x.env")])
    assert literals == {"TEXT": 'a\\b "q" $x'}


@pytest.mark.parametrize("line", ['TEXT="value"garbage', "TEXT", "TEXT=a\x00b"])
def test_malformed_lines_refuse_before_the_command_runs(tmp_path, line, capsys):
    """Bug: a typo in an env file runs the command with a misread environment or a traceback."""
    (tmp_path / "x.env").write_text(line + "\n")
    code = secret_run.main(["run", "--env-file", str(tmp_path / "x.env"), "--", "/bin/echo", "RAN"])
    out, err = capsys.readouterr()
    assert code in (2, 127) and "RAN" not in out and err.startswith("op run:")


def test_multi_line_quoted_value_is_refused_not_misread(tmp_path):
    """Bug: a quoted multi-line value silently becomes a one-line secret reference."""
    (tmp_path / "x.env").write_text('KEY="first line\nsecond line"\n')
    with pytest.raises(ValueError, match="multi-line"):
        secret_run.environment([str(tmp_path / "x.env")])


@pytest.mark.parametrize("value", ["op://A/B", "op://A/B/C?x y", "op://A/B/C/D/E"])
def test_malformed_references_are_refused_before_submission(tmp_path, value):
    """Bug: a malformed reference reaches the notification and the audit log."""
    (tmp_path / "x.env").write_text(f"X={value}\n")
    with pytest.raises(ValueError):
        secret_run.environment([str(tmp_path / "x.env")])


@pytest.mark.parametrize(
    "args",
    [
        ["read", "op://A/B/C"],
        ["inject"],
        ["item", "get", "X"],
        ["item", "share", "X"],
        ["--account", "example", "item", "share", "X"],
        ["document", "get", "X"],
        ["--format=json", "read", "op://A/B/C"],
        ["item", "--format=json", "get", "X"],
        ["--account", "example", "run", "--", "true"],
    ],
)
def test_value_printing_commands_are_refused_whatever_flags_surround_them(
    args, capsys, marked_session
):
    """Bug: an agent prints a secret through a subcommand hidden behind a global flag."""
    assert secret_run.main(args) == 1
    assert "is refused for agents" in capsys.readouterr().err
    assert marked_session == []


def real(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "op").write_text("#!/bin/sh\necho REAL_OP\n")
    (real / "op").chmod(0o755)
    return real


def test_other_subcommands_pass_to_the_real_op(tmp_path, monkeypatch, marked_session):
    """Bug: op --version or op whoami stop working, or the launcher calls itself forever."""
    own = tmp_path / "bin"
    own.mkdir()
    (own / "op").write_text("#!/bin/sh\n")
    (own / "op").chmod(0o755)
    monkeypatch.setenv("PATH", f"{own}{os.pathsep}{real(tmp_path)}")
    monkeypatch.setenv(secret_run.LAUNCHER, str(own / "op"))
    monkeypatch.setattr("sys.argv", ["/elsewhere/python"])
    secret_run.main(["--version"])
    assert marked_session == [(tmp_path / "real/op", [str(tmp_path / "real/op"), "--version"])]


def test_unmarked_session_is_the_real_op(tmp_path, monkeypatch, marked_session):
    """Bug: the operator's own terminal routes op run through the phone or refuses op signin."""
    monkeypatch.delenv(secret_run.MARK)
    monkeypatch.setenv("PATH", str(real(tmp_path)))
    secret_run.main(["read", "op://A/B/C"])
    secret_run.main(["run", "--", "true"])
    secret_run.main(["item", "share", "X"])
    assert [argv[1:] for _, argv in marked_session] == [
        ["read", "op://A/B/C"],
        ["run", "--", "true"],
        ["item", "share", "X"],
    ]


def test_missing_real_op_is_named(tmp_path, monkeypatch, capsys):
    """Bug: a pass-through on a machine without op fails with a traceback."""
    monkeypatch.setattr("sys.argv", [str(tmp_path / "op"), "--version"])
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


def test_unreachable_broker_names_the_missing_step(tmp_path, monkeypatch, capsys):
    """Bug: an agent on a machine without the route gets a vague failure and retries blindly."""
    monkeypatch.setattr(secret_transport, "SOCKET", tmp_path / "absent.sock")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / "x.env").write_text("X=op://A/B/C\n")
    assert secret_run.main(["run", "--env-file", str(tmp_path / "x.env"), "--", "true"]) == 1
    err = capsys.readouterr().err
    assert "unreachable" in err and "no SSH route" in err and "operator" in err
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh/slopmeister-remote.conf").write_text("Host one\nHost two\nHost *\n")
    assert secret_run.main(["run", "--env-file", str(tmp_path / "x.env"), "--", "true"]) == 1
    assert "exactly one alias" in capsys.readouterr().err


@pytest.mark.parametrize("literal", (False, True))
def test_command_without_references_cannot_bypass_native_approval(tmp_path, capsys, literal):
    """Bug: the allowed wrapper executes a command without any broker or native approval."""
    env = tmp_path / "literal.env"
    env.write_text("PLAIN=example\n")
    marker = tmp_path / "ran"
    args = ["--env-file", str(env)] if literal else []
    code = secret_run.main(
        ["run", *args, "--", "/bin/sh", "-c", 'echo RAN > "$1"', "_", str(marker)]
    )
    assert code == 2 and not marker.exists()
    out, err = capsys.readouterr()
    assert out == "" and "run the command directly" in err
