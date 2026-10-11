"""Service-action supervisors constrain credentials, processes, and diagnostics."""

import json
import os
from pathlib import Path
import sys

import pytest

from tests.integration.install.helpers import consumer


def test_pat_only_supervisor_never_reads_a_certificate_or_password(tmp_path, monkeypatch):
    module, data, _ = consumer(tmp_path, monkeypatch)
    del data["password_ref"], data["certificate_document"]
    data["origin"] += "/jira"
    (tmp_path / "config.json").write_text(json.dumps(data))
    calls = []

    def invoke(run):
        calls.append(run.argv[1])
        if run.argv[1] == "user":
            return json.dumps(
                dict(id=data["account_id"], type="SERVICE_ACCOUNT", state="ACTIVE")
            ).encode()
        if run.argv[1] == "vault":
            return json.dumps([dict(id=data["vault_id"], name=data["vault_name"])]).encode()
        assert run.argv[1:3] == ["run", "--"] and "JIRA_CERT_PASSWORD" not in run.env
        assert "pfx" not in json.loads(run.payload)
        return b'{"result":"JIRA_CONTEXT_PASS"}'

    monkeypatch.setattr(module, "invoke", invoke)
    assert json.loads(module.fetch())["result"] == "JIRA_CONTEXT_PASS"
    assert calls == ["user", "vault", "run"]


def test_supervisor_uses_only_selected_vault_and_never_inherits_desktop_credentials(
    tmp_path, monkeypatch
):
    module, data, _ = consumer(tmp_path, monkeypatch)
    monkeypatch.setenv("OP_SESSION_private", "DESKTOP_CANARY")
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "PARENT_CANARY")
    monkeypatch.setenv("OP_BIOMETRIC_UNLOCK_ENABLED", "true")
    calls = []

    def invoke(run):
        calls.append((run.argv, run.env.copy(), run.payload))
        assert "DESKTOP_CANARY" not in str(run.env) and "PARENT_CANARY" not in str(run.env)
        if run.argv[1:3] == ["user", "get"]:
            return json.dumps(
                dict(id=data["account_id"], type="SERVICE_ACCOUNT", state="ACTIVE")
            ).encode()
        if run.argv[1:3] == ["vault", "list"]:
            return json.dumps([dict(id=data["vault_id"], name=data["vault_name"])]).encode()
        if run.argv[1:3] == ["document", "get"]:
            return b"SYNTHETIC_P12"
        assert run.env["JIRA_PAT"] == data["pat_ref"]
        assert run.argv[-2:] == ["-m", "service_actions.provider"]
        assert run.cwd == tmp_path
        assert run.argv[3:6] == ["/usr/bin/env", "-u", "OP_SERVICE_ACCOUNT_TOKEN"]
        return b'{"result":"JIRA_CONTEXT_PASS","user":"reader","total":0,"tickets":[]}'

    monkeypatch.setattr(module, "invoke", invoke)
    assert json.loads(module.fetch())["result"] == "JIRA_CONTEXT_PASS"
    assert len(calls) == 4 and not list(tmp_path.glob("*.p12"))


@pytest.mark.parametrize("platform,home", [("darwin", "/var/empty"), ("linux", str(Path.home()))])
def test_op_receives_a_home_that_fits_the_system(tmp_path, monkeypatch, platform, home):
    """Bug: op gets the real home on macOS, or a folder Linux does not have."""
    module, data, _ = consumer(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "platform", platform)
    homes = []

    def invoke(run):
        homes.append((run.env.get("HOME"), run.env.get("XDG_CONFIG_HOME")))
        if run.argv[1] == "user":
            return json.dumps(
                dict(id=data["account_id"], type="SERVICE_ACCOUNT", state="ACTIVE")
            ).encode()
        if run.argv[1] == "vault":
            return json.dumps([dict(id=data["vault_id"], name=data["vault_name"])]).encode()
        if run.argv[1] == "document":
            return b"p12"
        return b'{"result":"JIRA_CONTEXT_PASS"}'

    monkeypatch.setattr(module, "invoke", invoke)
    module.fetch()
    config = str(Path.home() / ".config")
    assert homes == [(home, config)] * 4


@pytest.mark.parametrize("unsafe", ["missing", "permissions", "symlink"])
def test_invalid_token_file_fails_without_any_op_fallback(tmp_path, monkeypatch, unsafe):
    module, _, token = consumer(tmp_path, monkeypatch)
    if unsafe == "missing":
        token.unlink()
    elif unsafe == "permissions":
        token.chmod(0o644)
    else:
        saved = token.with_suffix(".saved")
        token.rename(saved)
        token.symlink_to(saved)
    monkeypatch.setattr(module, "invoke", lambda *args, **kwargs: pytest.fail("op must not run"))
    with pytest.raises(ValueError):
        module.fetch()


def test_removed_runtime_dependency_stops_before_token_or_provider(tmp_path, monkeypatch):
    module, _, _ = consumer(tmp_path, monkeypatch)
    monkeypatch.setattr(
        module.runtime,
        "require",
        lambda **_kwargs: (_ for _ in ()).throw(
            ValueError("LOCAL_PREREQUISITE_MISSING:/usr/bin/curl")
        ),
    )
    monkeypatch.setattr(module, "service_token", lambda *_args: pytest.fail("token was read"))
    monkeypatch.setattr(module, "invoke", lambda *_args, **_kwargs: pytest.fail("child started"))
    with pytest.raises(ValueError, match="^LOCAL_PREREQUISITE_MISSING:/usr/bin/curl$"):
        module.fetch()


@pytest.mark.parametrize("certificate", [False, True])
def test_certificate_admission_precedes_all_credentials(tmp_path, monkeypatch, certificate):
    """Bug: a missing Linux legacy provider is found only after reading credentials."""
    module, data, _ = consumer(tmp_path, monkeypatch)
    if not certificate:
        del data["certificate_document"], data["password_ref"]
    (tmp_path / "config.json").write_text(json.dumps(data))

    def require(**kwargs):
        assert kwargs.get("cert") is certificate
        raise ValueError("LOCAL_PREREQUISITE_MISSING:OpenSSL legacy provider")

    monkeypatch.setattr(module.runtime, "require", require)
    monkeypatch.setattr(module, "service_token", lambda _: pytest.fail("token was read"))
    monkeypatch.setattr(module, "invoke", lambda _: pytest.fail("credential child started"))
    with pytest.raises(ValueError, match="LOCAL_PREREQUISITE_MISSING:OpenSSL legacy provider"):
        module.fetch()


@pytest.mark.parametrize("wrong", ["identity", "vault"])
def test_wrong_service_identity_or_vault_stops_before_secret_resolution(
    tmp_path, monkeypatch, wrong
):
    module, data, _ = consumer(tmp_path, monkeypatch)

    def invoke(run):
        if run.argv[1:3] == ["user", "get"]:
            identity = "C" * 26 if wrong == "identity" else data["account_id"]
            return json.dumps(dict(id=identity, type="SERVICE_ACCOUNT", state="ACTIVE")).encode()
        return json.dumps([dict(id="c" * 26, name="Other")]).encode()

    monkeypatch.setattr(module, "invoke", invoke)
    expected = (
        "SERVICE_ACCOUNT_IDENTITY_MISMATCH" if wrong == "identity" else "VAULT_SCOPE_MISMATCH"
    )
    with pytest.raises(ValueError, match="^" + expected + "$"):
        module.fetch()


def test_http_child_never_receives_the_service_account_or_parent_environment(tmp_path, monkeypatch):
    module, data, _ = consumer(tmp_path, monkeypatch)
    seen = []

    def invoke(run):
        if run.argv[1] == "user":
            return json.dumps(
                dict(id=data["account_id"], type="SERVICE_ACCOUNT", state="ACTIVE")
            ).encode()
        if run.argv[1] == "vault":
            return json.dumps([dict(id=data["vault_id"], name=data["vault_name"])]).encode()
        if run.argv[1] == "document":
            return b"p12"
        seen.append(run)
        return b'{"result":"JIRA_CONTEXT_PASS"}'

    monkeypatch.setattr(module, "invoke", invoke)
    module.fetch()
    assert len(seen) == 1
    assert seen[0].argv[3:6] == ["/usr/bin/env", "-u", "OP_SERVICE_ACCOUNT_TOKEN"]
    assert "OP_SESSION_private" not in seen[0].env


@pytest.mark.parametrize(
    "mode,expected,timeout",
    [("output", "ACTION_OUTPUT_LIMIT", 10), ("timeout", "ACTION_TIMEOUT", 0.2)],
)
def test_subprocess_output_and_wall_time_are_bounded(
    tmp_path, monkeypatch, mode, expected, timeout
):
    module, _, _ = consumer(tmp_path, monkeypatch)
    code = 'print("x" * (3 * 1024 * 1024))' if mode == "output" else "import time; time.sleep(10)"
    with pytest.raises(ValueError, match=expected):
        module.invoke(
            module.Run(
                [module.sys.executable, "-c", code], {"PATH": module.BASE_PATH}, timeout=timeout
            )
        )


@pytest.mark.parametrize(
    "output,expected",
    [
        ('{"result":"HTTP_403"}', "HTTP_403"),
        *[
            (json.dumps({"result": code}), code)
            for code in (
                "ACTION_TIMEOUT",
                "ACTION_OUTPUT_LIMIT",
                "REQUEST_INVALID",
                "CONFIG_INVALID",
                "RELATED_LIMIT",
                "INPUT_INVALID",
            )
        ],
        ("secret upstream diagnostics", "SERVICE_ACCOUNT_ACCESS_FAILED"),
        ('{"result":"PRIVATE_CANARY"}', "SERVICE_ACCOUNT_ACCESS_FAILED"),
    ],
)
@pytest.mark.parametrize("payload", [b"", b"x" * (1024 * 1024)], ids=["empty", "unconsumed"])
def test_failure_diagnostics_only_release_known_codes(
    tmp_path, monkeypatch, output, expected, payload
):
    """Bug: early stdin closure loses the known failure code or releases private diagnostics."""
    module, _, _ = consumer(tmp_path, monkeypatch)
    argv = [module.sys.executable, "-c", "import sys; print(sys.argv[1]); sys.exit(1)", output]
    with pytest.raises(ValueError, match="^" + expected + "$"):
        module.invoke(
            module.Run(
                argv,
                {"PATH": module.BASE_PATH},
                payload=payload,
                failure="SERVICE_ACCOUNT_ACCESS_FAILED",
            )
        )


def test_consumer_subprocess_keeps_terminal_session_and_owns_cancellable_group(
    tmp_path, monkeypatch
):
    module, _, _ = consumer(tmp_path, monkeypatch)
    code = "import os,json; print(json.dumps([os.getsid(0),os.getpgrp(),os.getpid()]))"
    session, group, pid = json.loads(
        module.invoke(module.Run([module.sys.executable, "-c", code], {"PATH": module.BASE_PATH}))
    )
    assert session == os.getsid(0) and group == pid
