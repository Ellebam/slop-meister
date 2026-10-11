"""Doctor answers that need no scratch home. Each names the bug that escapes without it."""

import pytest

from slopmeister import cli
from slopmeister.workstation import doctor, host
from tests.support.fakes import fake_binary, path_with


@pytest.mark.parametrize("fixed", ["missing", "executable", "not-executable"])
def test_codex_requires_the_fixed_launcher_path(tmp_path, monkeypatch, fixed):
    monkeypatch.setenv("HOME", str(tmp_path))
    prefix = tmp_path / "homebrew/bin"
    fake_binary(prefix, "codex", "exit 0")
    monkeypatch.setenv("PATH", str(prefix))
    if fixed != "missing":
        binary = fake_binary(tmp_path / ".local/bin", "codex", "exit 0")
        if fixed == "not-executable":
            binary.chmod(0o600)
    found = doctor._tool("codex")
    assert found.status == ("ok" if fixed == "executable" else "problem")
    if found.status == "problem":
        assert "~/.local/bin/codex" in found.evidence + found.fix


@pytest.mark.parametrize("tool", ("shellcheck", "jq"))
def test_missing_linux_system_tool_needs_the_operator(tmp_path, monkeypatch, tool):
    monkeypatch.setenv("SLOPMEISTER_PLATFORM", "linux")
    monkeypatch.setenv("PATH", str(tmp_path))
    assert tool in doctor.TOOLS
    found = doctor._tool(tool)
    assert found.status == "problem" and found.evidence == "not on PATH"
    assert "ask the operator" in found.fix


def test_old_python_names_the_floor_before_any_command_loads():
    """Escaping bug, a new Mac's system python3 crashes on import instead of naming the floor."""
    assert cli.python_problem((3, 9, 6)) == (
        "Python 3.14 or newer is required, python3 here is 3.9.6"
    )
    assert cli.python_problem((3, 14, 0)) is None


def test_vault_precedence_is_argument_then_environment_then_default(tmp_path, monkeypatch):
    """Escaping bug, the chosen vault is validated but a later task receives another path."""
    monkeypatch.setenv("SLOPMEISTER_VAULT", str(tmp_path / "from-env"))
    assert doctor.vault_path(str(tmp_path / "from-cli"), tmp_path) == tmp_path / "from-cli"
    assert doctor.vault_path(None, tmp_path) == tmp_path / "from-env"
    monkeypatch.setenv("SLOPMEISTER_VAULT", "")
    assert doctor.vault_path(None, tmp_path) == tmp_path / ".slopmeister/vault"


def test_invalid_vaults_are_refused(tmp_path):
    assert "Directory not found" in doctor.vault_problem(tmp_path / "missing")
    (tmp_path / "empty/_system").mkdir(parents=True)
    assert "No Markdown files" in doctor.vault_problem(tmp_path / "empty")
    (tmp_path / "empty/_system/start.md").write_text("# Fixture\n")
    assert doctor.vault_problem(tmp_path / "empty") is None


@pytest.mark.parametrize("tool", ["gh", "glab"])
def test_hanging_probe_is_unknown_not_a_hang(tmp_path, monkeypatch, tool):
    """Bug: one stuck launchctl, gh or glab call stalls the whole report or reads as ok."""
    fake_binary(tmp_path, tool, "sleep 5")
    monkeypatch.setenv("PATH", path_with(tmp_path))
    monkeypatch.setattr(host, "TIMEOUT", 0.2)
    found = doctor.cli_login(tool)
    assert found.status == "unknown"
    assert "timed out" in found.evidence


@pytest.mark.parametrize("reply", ["not json", '{"other": true}'])
def test_unreadable_claude_login_is_unknown(tmp_path, monkeypatch, reply):
    """Bug: an unexpected auth reply reads as logged in, or as logged out when it is not."""
    fake_binary(tmp_path, "claude", f"printf '%s\\n' '{reply}'")
    monkeypatch.setenv("PATH", path_with(tmp_path))
    assert doctor.claude_login().status == "unknown"


@pytest.mark.parametrize(
    ("code", "logged_in", "expected"),
    [(1, "true", "unknown"), (1, "false", "problem"), (0, "true", "ok")],
)
def test_claude_login_needs_a_clean_exit_to_be_ok(tmp_path, monkeypatch, code, logged_in, expected):
    """Bug: a failed claude auth status that still printed loggedIn=true read as logged in."""
    fake_binary(tmp_path, "claude", f"printf '{{\"loggedIn\": {logged_in}}}\\n'; exit {code}")
    monkeypatch.setenv("PATH", path_with(tmp_path))
    assert doctor.claude_login().status == expected


def test_missing_login_tool_is_unknown_not_a_second_problem(tmp_path, monkeypatch):
    """Bug: a missing gh or glab is blamed twice, once as a tool and once as a login."""
    monkeypatch.setenv("PATH", str(tmp_path))
    assert doctor.cli_login("gh").status == "unknown"
    assert doctor.cli_login("glab").status == "unknown"
    assert doctor.claude_login().status == "unknown"


def test_glab_is_logged_in_when_one_host_is_despite_the_unused_default_host(tmp_path, monkeypatch):
    """Bug: glab fails the unused gitlab.com entry and exits 1, so a working login reads broken."""
    fake_binary(tmp_path, "glab", "echo 'x gitlab.com: 401'; echo 'Logged in to h as u'; exit 1")
    monkeypatch.setenv("PATH", path_with(tmp_path))
    found = doctor.cli_login("glab")
    assert found.status == "ok"
    assert found.evidence == "glab auth status exited 1, one host is logged in"
    fake_binary(tmp_path, "gh", "echo 'Logged in to h as u'; exit 1")
    assert doctor.cli_login("gh").status == "problem"
