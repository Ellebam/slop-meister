"""The tier of a request picks the token, and tier two waits for the operator twice."""

import os
from pathlib import Path

import pytest

from slopmeister.session import secret_approval, secret_run, secret_tier
from tests.support.op_session import ONE, TWO, approve, env_file

pytestmark = pytest.mark.usefixtures("session")


def test_tier_one_runs_the_real_op_with_its_token_and_no_question(tmp_path, monkeypatch, session):
    """Bug: an everyday secret waits for the phone, or the command inherits the token."""
    monkeypatch.setenv("OP_RUN_NO_MASKING", "true")
    monkeypatch.setenv("OP_CONNECT_HOST", "https://connect.invalid")
    monkeypatch.setenv("OP_CONNECT_TOKEN", "other-account")
    text = "DEMO=op://everyday/Item/credential\nPLAIN=literal\n"
    assert secret_run.main(env_file(tmp_path, text)) is None
    ((argv, env),) = session
    assert argv[1:] == [
        "run",
        "--",
        "/usr/bin/env",
        "-u",
        "OP_SERVICE_ACCOUNT_TOKEN",
        "deploy",
        "now",
    ]
    assert env[secret_run.TOKEN] == ONE
    assert env["DEMO"] == "op://everyday/Item/credential" and env["PLAIN"] == "literal"
    # Bug: an inherited variable unmasks the output or swaps the account behind the chosen token.
    assert not set(secret_run.OVERRIDES) & set(env)


def test_tier_two_without_the_operators_word_releases_nothing(tmp_path, capsys, session):
    """Bug: a production secret resolves on the task's own intent."""
    assert secret_run.main(env_file(tmp_path, "DEMO=op://Production/Item/credential\n")) == 1
    assert "op tier-two -- <command>" in capsys.readouterr().err
    assert session == []


@pytest.mark.parametrize(
    "text",
    ["DEMO=op://Production/Item/credential\n", "A=op://Everyday/I/f\nB=op://idtwo/I/f\n"],
)
def test_tier_two_runs_with_its_token_after_the_approval(tmp_path, monkeypatch, session, text):
    """Bug: a request naming both tiers takes the tier-one token, or skips the approval."""
    monkeypatch.setenv(secret_run.ROUTE, secret_run.TIER_TWO)
    monkeypatch.setenv("SECRET_ASK_REASON", "Deploy the host")
    asked = approve(monkeypatch, "approved")
    assert secret_run.main(env_file(tmp_path, text)) is None
    ((_, env),) = session
    assert env[secret_run.TOKEN] == TWO
    (body,) = asked
    for shown in ("Command: deploy now", "op://", "Session:", "Host:"):
        assert shown in body["message"]
    # Bug: the preview on the phone shows a command before it says why and who asks.
    assert body["message"].startswith("Why: Deploy the host\nSession: ")


def test_env_file_changes_during_approval_do_not_change_the_request(tmp_path, monkeypatch, session):
    """A writer changes an env file while the phone waits. Only the shown reference may run."""
    monkeypatch.setenv(secret_run.ROUTE, secret_run.TIER_TWO)
    monkeypatch.setenv("SECRET_ASK_REASON", "Deploy the host")
    asked = approve(monkeypatch, "approved")
    line = env_file(tmp_path, "DEMO=op://Production/Original/credential\nPLAIN=original\n")

    def decision(settings, identifier):
        (tmp_path / "x.env").write_text("DEMO=op://Production/Changed/credential\nPLAIN=changed\n")
        return "approved"

    monkeypatch.setattr(secret_approval, "decision", decision)
    assert secret_run.main(line) is None
    assert "op://Production/Original/credential" in asked[0]["message"]
    assert session[0][1]["DEMO"] == "op://Production/Original/credential"
    assert session[0][1]["PLAIN"] == "original"


@pytest.mark.parametrize("reason", [None, "", " \n "])
def test_tier_two_without_a_reason_asks_nothing(tmp_path, monkeypatch, capsys, session, reason):
    """Bug: the operator is asked to approve a command whose purpose nobody stated."""
    monkeypatch.setenv(secret_run.ROUTE, secret_run.TIER_TWO)
    if reason is None:
        monkeypatch.delenv("SECRET_ASK_REASON", raising=False)
    else:
        monkeypatch.setenv("SECRET_ASK_REASON", reason)
    asked = approve(monkeypatch, "approved")
    assert secret_run.main(env_file(tmp_path, "DEMO=op://Production/Item/credential\n")) == 1
    err = capsys.readouterr().err
    assert 'SECRET_ASK_REASON="<one line>"' in err and "op desktop" not in err
    assert asked == [] and session == []


def test_reason_cannot_write_lines_of_its_own(tmp_path, monkeypatch, session):
    """Bug: a reason with a line break shows a second, forged command above the real one."""
    monkeypatch.setenv(secret_run.ROUTE, secret_run.TIER_TWO)
    monkeypatch.setenv("SECRET_ASK_REASON", "Deploy\nCommand: harmless\r\nHost:\tother")
    asked = approve(monkeypatch, "approved")
    assert secret_run.main(env_file(tmp_path, "DEMO=op://Production/Item/credential\n")) is None
    lines = asked[0]["message"].splitlines()
    assert lines[0] == "Why: Deploy Command: harmless Host: other"
    labels = ["Why", "Session", "Host", "Command", "References", "Directory"]
    assert [line.partition(":")[0] for line in lines] == labels


@pytest.mark.parametrize("state", ["denied", "timed out"])
def test_deny_and_silence_release_nothing(tmp_path, monkeypatch, capsys, session, state):
    """Bug: a denial or ten minutes of silence still starts the command."""
    monkeypatch.setenv(secret_run.ROUTE, secret_run.TIER_TWO)
    monkeypatch.setenv("SECRET_ASK_REASON", "Deploy the host")
    approve(monkeypatch, state)
    assert secret_run.main(env_file(tmp_path, "DEMO=op://Production/Item/credential\n")) == 1
    assert state in capsys.readouterr().err
    assert session == []


def test_home_assistant_down_names_the_desktop_route(tmp_path, monkeypatch, capsys, session):
    """Bug: with Home Assistant stopped the agent retries blindly and tells no one."""
    monkeypatch.setenv(secret_run.ROUTE, secret_run.TIER_TWO)
    monkeypatch.setenv("SECRET_ASK_REASON", "Deploy the host")
    approve(monkeypatch, "approved")

    def down(settings, body):
        raise secret_approval.Unreachable("connection refused")

    monkeypatch.setattr(secret_approval, "ask", down)
    assert secret_run.main(env_file(tmp_path, "DEMO=op://Production/Item/credential\n")) == 1
    err = capsys.readouterr().err
    assert "connection refused" in err and "op desktop -- <command>" in err
    assert session == []


def test_vault_in_no_tier_is_named(tmp_path, capsys, session):
    """Bug: an unknown vault falls into a tier, or fails without naming the vault."""
    assert secret_run.main(env_file(tmp_path, "DEMO=op://Stranger/Item/credential\n")) == 1
    err = capsys.readouterr().err
    assert "the vault Stranger is in no tier" in err and "op desktop" in err
    assert session == []


def test_desktop_route_hands_the_line_to_the_real_op(tmp_path, monkeypatch, capsys, session):
    """Bug: the ordered desktop route still uses a token, or lets masking be switched off."""
    monkeypatch.setenv(secret_run.ROUTE, secret_run.DESKTOP)
    monkeypatch.setenv(secret_run.TOKEN, "ops_inherited")
    monkeypatch.setenv("OP_RUN_NO_MASKING", "true")
    line = env_file(tmp_path, "DEMO=op://Stranger/Item/credential\n")
    assert secret_run.main(line) is None
    ((argv, env),) = session
    assert argv[1:] == line and secret_run.TOKEN not in env and "OP_RUN_NO_MASKING" not in env
    for spelling in ("--no-masking", "--no-masking=true"):
        assert secret_run.main(["run", spelling, "--", "true"]) == 2
        assert "--no-masking is refused" in capsys.readouterr().err
    # After the separator the word belongs to the command, not to op.
    assert secret_run.main(["run", "--", "echo", "--no-masking=true"]) is None
    assert len(session) == 2


@pytest.mark.parametrize("name", ["tier-two", "desktop"])
def test_route_word_sets_the_route_for_its_command(session, name):
    """Bug: the operator's word does not reach an op run inside a Task target."""
    assert secret_run.main([name, "--", "task", "deploy"]) is None
    ((argv, env),) = session
    assert argv == ["task", "deploy"] and env[secret_run.ROUTE] == name


@pytest.mark.parametrize("above", [secret_run.INSIDE, secret_run.ROUTE])
def test_route_word_below_op_run_or_another_route_is_refused(monkeypatch, capsys, session, above):
    """Bug: op run -- op tier-two rides the allowed op run prefix past the intent rule."""
    monkeypatch.setenv(above, "1")
    assert secret_run.main(["tier-two", "--", "task", "deploy"]) == 1
    assert "must be the outermost command" in capsys.readouterr().err
    assert secret_run.main(["desktop", "task", "deploy"]) == 2
    assert session == []


def test_command_of_an_op_run_is_marked(tmp_path, session):
    """Bug: a route word inside the command of an op run cannot be told from an outer one."""
    secret_run.main(env_file(tmp_path, "DEMO=op://Everyday/Item/credential\n"))
    assert session[0][1][secret_run.INSIDE] == "1"


def test_line_without_references_needs_no_1password(session):
    """Bug: an op run line with only literal variables needs a token or waits for an approval."""
    (Path.home() / secret_tier.DIRECTORY / secret_tier.LISTS).unlink()
    assert secret_run.main(["run", "--", "/bin/sh", "-c", "echo PLAIN_RUN"]) is None
    ((argv, env),) = session
    assert argv == ["/bin/sh", "-c", "echo PLAIN_RUN"] and secret_run.TOKEN not in env


@pytest.mark.parametrize(
    "line",
    [
        "OP_SERVICE_ACCOUNT_TOKEN=ops_tier-two-synthetic",
        "OP_RUN_NO_MASKING=true",
        "OP_CONNECT_HOST=https://connect.invalid",
        "OP_CONNECT_TOKEN=op://Everyday/Connect/token",
        "SLOPMEISTER_OP_ROUTE=tier-two",
    ],
)
def test_env_file_cannot_set_what_the_ops_decision_rests_on(tmp_path, capsys, session, line):
    """Bug: an env file swaps the chosen token, unmasks the output or claims the operator's word."""
    text = f"DEMO=op://Everyday/Item/credential\n{line}\n"
    assert secret_run.main(env_file(tmp_path, text)) == 1
    name = line.partition("=")[0]
    assert f"{name} is set by the session's op and cannot come from an env file" in (
        capsys.readouterr().err
    )
    assert session == []


@pytest.mark.parametrize("mode", [0o644, 0o640])
def test_token_file_cannot_be_read_by_another_account(tmp_path, mode):
    """Bug: a token readable by another account quietly becomes the service credential."""
    token = tmp_path / "token"
    token.write_text("synthetic")
    token.chmod(mode)
    with pytest.raises(ValueError):
        secret_tier.private(token)


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_linked_token_file_is_refused(tmp_path, kind):
    """Bug: a credential path reads a file shared with another path."""
    target = tmp_path / "token"
    target.write_text("synthetic")
    target.chmod(0o600)
    link = tmp_path / "link"
    if kind == "symlink":
        link.symlink_to(target)
    else:
        os.link(target, link)
    with pytest.raises(ValueError):
        secret_tier.private(link)
