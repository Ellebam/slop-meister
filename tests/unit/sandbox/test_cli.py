"""Sandbox secrets never reach a process argument, and tokens land in the shared vault."""

import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from slopmeister.sandbox import cli
from slopmeister.session.service_actions.constants import PYTHON, PYTHON_FLAGS

ROUTE = {"account_id": "A" * 26, "vault_id": "b" * 26, "vault_name": "Automation"}
ROUTE |= {"token_file": "/private/credentials/service.env"}


@pytest.fixture
def calls(tmp_path, monkeypatch):
    seen = []

    def run(argv, **kwargs):
        seen.append((argv, kwargs.get("input")))
        if argv[0] == cli.OPENSSL:
            (tmp_path / "state/tls/key.pem").write_text("key")
            (tmp_path / "state/tls/cert.pem").write_text("cert")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cli, "STATE", tmp_path / "state")
    monkeypatch.setattr(cli, "ACCESS", tmp_path / "access")
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(cli.secrets, "token_urlsafe", lambda _size: "SENTINEL_DB_PASSWORD")
    return seen


def test_database_password_reaches_only_the_owner_only_env_file(calls, tmp_path):
    cli.prepare_state()
    cli._run(cli.compose("up", "-d"))
    env_file = tmp_path / "state/db.env"
    assert "SENTINEL_DB_PASSWORD" in env_file.read_text()
    assert env_file.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "state").stat().st_mode & 0o777 == 0o700
    assert calls and all("SENTINEL_DB_PASSWORD" not in " ".join(argv) for argv, _ in calls)


@pytest.mark.parametrize("existing", [False, True])
def test_sandbox_pin_is_not_group_writable_under_a_shared_group_umask(calls, existing):
    """Bug: the operator's sandbox pin is refused under the Linux account's umask 0002."""
    if existing:
        cli.prepare_state()
        (cli.STATE / "tls/cert.pem").chmod(0o664)
    previous = os.umask(0o002)
    try:
        cli.prepare_state()
    finally:
        os.umask(previous)
    assert (cli.STATE / "tls/cert.pem").stat().st_mode & 0o777 == 0o644


def test_pat_reaches_op_only_on_stdin_and_the_profile_only_as_a_reference(calls, tmp_path):
    cli._store("jira-read", "SENTINEL_PAT", ROUTE)
    cli._profile("jira-read", ROUTE)
    assert all("SENTINEL_PAT" not in " ".join(argv) for argv, _ in calls)
    assert json.loads(calls[-1][1])["fields"][0]["value"] == "SENTINEL_PAT"
    profile = json.loads((tmp_path / "access/sandbox/jira-read.json").read_text())
    assert "SENTINEL_PAT" not in json.dumps(profile)
    assert profile["pat_ref"] == "op://Automation/slopmeister-sandbox-jira-pat/credential"
    assert profile["server_ca"] == str(tmp_path / "state/tls/cert.pem")


def test_sandbox_setup_keeps_one_connection_profile_per_service(calls, tmp_path, monkeypatch):
    """Bug: setup keeps generating duplicate write profiles after writers reuse connections."""
    (tmp_path / "state").mkdir()
    (tmp_path / "state/ids.json").write_text("{}")
    monkeypatch.setattr(cli, "routing", lambda: ROUTE)
    monkeypatch.setattr(cli, "prepare_state", lambda: None)
    monkeypatch.setattr(cli, "_apps", lambda: {"jira-read": None, "confluence-read": None})
    monkeypatch.setattr(cli.setup, "wait", lambda _app: "RUNNING")
    cli.up()
    assert {p.name for p in (tmp_path / "access/sandbox").iterdir()} == {
        "jira-read.json",
        "confluence-read.json",
    }


def _profile(root, plot, action, route):
    (root / plot).mkdir(parents=True, exist_ok=True)
    (root / plot / f"{action}.json").write_text(json.dumps(route))


def test_routing_copies_the_one_shared_service_account(tmp_path):
    _profile(tmp_path, "field", "jira-read", ROUTE)
    _profile(tmp_path, "sandbox", "jira-read", dict(ROUTE, vault_id="c" * 26))
    _profile(tmp_path, "example-app", "jira-assigned", dict(ROUTE, vault_id="d" * 26))
    assert cli.routing(tmp_path) == ROUTE


@pytest.mark.parametrize("key", ["account_id", "vault_id", "token_file"])
def test_routing_refuses_profiles_that_disagree(tmp_path, key):
    _profile(tmp_path, "one", "jira-read", ROUTE)
    _profile(tmp_path, "two", "confluence-read", dict(ROUTE, **{key: "other"}))
    with pytest.raises(cli.SandboxError):
        cli.routing(tmp_path)


def test_sandbox_calls_fixed_supervisor_with_structured_input(tmp_path, monkeypatch):
    """Bug: keeping the sandbox Taskfile delivers an unreviewed selected-read bypass."""
    seen = {}

    def run(argv, **kwargs):
        seen.update(argv=argv, options=kwargs)
        return SimpleNamespace(returncode=0, stdout='{"result":"JIRA_CONTEXT_PASS"}', stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    assert cli._call(tmp_path, "jira-read", ["--issue", "TEST-7"])["result"] == "JIRA_CONTEXT_PASS"
    assert seen["argv"] == [str(PYTHON), *PYTHON_FLAGS, "-m", "service_actions.supervisor"]
    assert seen["options"]["cwd"] == tmp_path / ".claude/service-actions/jira-read"
    assert json.loads(seen["options"]["env"]["SLOPMEISTER_SERVICE_ACTION_INPUT"]) == [
        "--issue",
        "TEST-7",
    ]
