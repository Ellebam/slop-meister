"""An optional pinned server CA narrows trust and cannot be swapped by another user."""

import json
import sys

import pytest

from slopmeister.install.service_actions import validate_profile
from tests.integration.install.helpers import consumer, profile


def _pinned(tmp_path, monkeypatch):
    module, data, _ = consumer(tmp_path, monkeypatch)
    del data["password_ref"], data["certificate_document"]
    ca = tmp_path / "localhost.pem"
    ca.write_text("SYNTHETIC CERTIFICATE\n")
    ca.chmod(0o600)
    data["server_ca"] = str(ca)
    (tmp_path / "config.json").write_text(json.dumps(data))
    return module, data, ca


def _op(data, payloads):
    def invoke(run):
        if run.argv[1] == "user":
            return json.dumps(
                dict(id=data["account_id"], type="SERVICE_ACCOUNT", state="ACTIVE")
            ).encode()
        if run.argv[1] == "vault":
            return json.dumps([dict(id=data["vault_id"], name=data["vault_name"])]).encode()
        if run.argv[1] == "document":
            return b"p12"
        payloads.append(json.loads(run.payload))
        return b'{"result":"JIRA_CONTEXT_PASS"}'

    return invoke


@pytest.mark.parametrize("keys", ["pat-only", "certificate"])
def test_profile_accepts_an_absolute_server_ca_beside_either_key_set(keys):
    data = dict(profile(), server_ca="/private/state/localhost.pem")
    if keys == "pat-only":
        del data["password_ref"], data["certificate_document"]
    assert validate_profile(data, "example", "jira-read") == data


def test_profile_rejects_a_relative_server_ca():
    with pytest.raises(ValueError):
        validate_profile(dict(profile(), server_ca="localhost.pem"), "example", "jira-read")


def test_supervisor_passes_a_safe_server_ca_to_the_provider(tmp_path, monkeypatch):
    module, data, ca = _pinned(tmp_path, monkeypatch)
    payloads = []
    monkeypatch.setattr(module, "invoke", _op(data, payloads))
    assert json.loads(module.fetch())["result"] == "JIRA_CONTEXT_PASS"
    assert payloads[0]["server_ca"] == str(ca)


def test_supervisor_without_server_ca_sends_none(tmp_path, monkeypatch):
    module, data, ca = _pinned(tmp_path, monkeypatch)
    del data["server_ca"]
    (tmp_path / "config.json").write_text(json.dumps(data))
    ca.chmod(0o666)
    payloads = []
    monkeypatch.setattr(module, "invoke", _op(data, payloads))
    module.fetch()
    assert "server_ca" not in payloads[0]


def _symlink(ca, data):
    saved = ca.with_suffix(".saved")
    ca.rename(saved)
    ca.symlink_to(saved)


UNSAFE = {
    "missing": lambda ca, data: ca.unlink(),
    "group-writable": lambda ca, data: ca.chmod(0o620),
    "symlink": _symlink,
    "relative": lambda ca, data: data.update(server_ca="localhost.pem"),
    "dir": lambda ca, data: data.update(server_ca=str(ca.parent)),
}


@pytest.mark.parametrize("unsafe", sorted(UNSAFE))
def test_swappable_server_ca_stops_before_the_provider(tmp_path, monkeypatch, unsafe):
    module, data, ca = _pinned(tmp_path, monkeypatch)
    UNSAFE[unsafe](ca, data)
    (tmp_path / "config.json").write_text(json.dumps(data))
    payloads = []
    monkeypatch.setattr(module, "invoke", _op(data, payloads))
    with pytest.raises(ValueError, match="LOCAL_CREDENTIAL_FILE_UNSAFE"):
        module.fetch()
    assert payloads == []


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_pin_with_client_certificate_stops_before_credentials_on_macos(
    tmp_path, monkeypatch, platform
):
    """Bug: a Mac profile loses the exclusive pin after its credentials are read."""
    module, data, _ = consumer(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "platform", platform)
    pin = tmp_path / "pin.pem"
    pin.write_text("SYNTHETIC CERTIFICATE\n")
    pin.chmod(0o600)
    data["server_ca"] = str(pin)
    (tmp_path / "config.json").write_text(json.dumps(data))
    payloads = []
    monkeypatch.setattr(module, "invoke", _op(data, payloads))
    if platform == "darwin":
        monkeypatch.setattr(module, "service_token", lambda _: pytest.fail("credentials read"))
        with pytest.raises(ValueError, match="CONFIG_INVALID"):
            module.fetch()
        assert payloads == []
    else:
        assert json.loads(module.fetch())["result"] == "JIRA_CONTEXT_PASS"
        assert len(payloads) == 1
