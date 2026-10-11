"""Approved native writes reach the complete consumer with synthetic credentials and HTTPS."""

from dataclasses import replace
import hashlib
import json
import tempfile
from urllib.parse import urlsplit

import pytest

from slopmeister.session.service_actions.constants import PYTHON
from tests.native.install.intent_fixture import claude_host, close, main_results
from tests.native.install.native_tool_fixture import prepared_native
from tests.native.install.test_service_actions_provider import _reply
from tests.support.service_actions import https_server, identity
from tests.support.standin import run

pytestmark = pytest.mark.xdist_group("native-standin")


def _profile(world, server):
    root = world.entry.parent
    config = root / "config.json"
    data = json.loads(config.read_text())
    for key in ("password_ref", "certificate_document"):
        data.pop(key)
    token = world.root / "synthetic.env"
    token.write_text("OP_SERVICE_ACCOUNT_TOKEN=ops_SYNTHETIC_CANARY\n")
    token.chmod(0o600)
    data.update(origin=server.origin, server_ca=str(server.ca_path), token_file=str(token))
    config.chmod(0o600)
    config.write_text(json.dumps(data))
    config.chmod(0o400)
    return data


def _credentials(world, server):
    root = world.entry.parent
    data = _profile(world, server)
    stub = world.root / "synthetic-op"
    calls = world.root / "credential-calls.jsonl"
    stub.write_text(
        f"#!{PYTHON}\nimport json,os,sys\n"
        + f"data={data!r}\n"
        + f"with open({str(calls)!r},'a') as f: f.write(json.dumps(sys.argv[1:])+ '\\n')\n"
        + "if sys.argv[1] == 'user':\n"
        + " print(json.dumps(dict(id=data['account_id'],type='SERVICE_ACCOUNT',state='ACTIVE')))\n"
        + "elif sys.argv[1] == 'vault':\n"
        + " print(json.dumps([dict(id=data['vault_id'],name=data['vault_name'])]))\n"
        + "elif sys.argv[1:3] == ['run','--']:\n"
        + " os.environ['JIRA_PAT']='disposable-pat'\n"
        + " os.execvpe(sys.argv[3],sys.argv[3:],os.environ)\n"
    )
    stub.chmod(0o700)
    constants = root / "service_actions/constants.py"
    source = constants.read_text() + f"\nOP = Path({str(stub)!r})\n"
    constants.chmod(0o644)
    constants.write_text(source)
    constants.chmod(0o444)
    return calls


def _page():
    return {
        "id": "7",
        "type": "page",
        "title": "Synthetic",
        "space": {"key": "TEST"},
        "version": {"number": 1, "by": {"username": "reader"}, "when": "2026-09-01T10:00:00Z"},
    }


def _provider(written):
    responses = {
        "/rest/api/2/myself": {"name": "reader"},
        "/rest/api/user/current": {"type": "known", "username": "reader"},
        "/rest/api/2/issue/TEST-7": {
            "key": "TEST-7",
            "fields": {"updated": "2026-09-01T10:00:00.000+0000"},
        },
        "/rest/api/content/7": _page(),
    }

    def callback(handler):
        path = urlsplit(handler.path).path
        if handler.command == "POST":
            body = handler.rfile.read(int(handler.headers["Content-Length"]))
            written.append((path, body))
            _reply(handler, {"id": "8", "version": {"number": 1}})
        else:
            _reply(handler, responses[path])

    return callback


@pytest.mark.parametrize("tool", ["claude", "codex"])
@pytest.mark.parametrize("action", ["jira-write", "confluence-write"])
@pytest.mark.parametrize("approved", [False, True])
def test_exact_native_approval_reaches_full_consumer_and_only_one_local_write(
    tmp_path, monkeypatch, tool, action, approved
):
    """Bug: marker proof hides broken credential setup, provider argv or native writer admission."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    world = prepared_native(tmp_path, tool, action)
    written = []
    try:
        with https_server(identity(), _provider(written), False) as server:
            calls = _credentials(world, server)
            name = "mcp__" + action.replace("-", "_") + "__run"
            world.server.script = [(name, {"command": world.command})]
            if tool == "claude":
                assert len(claude_host(world, approved)) == 1
            else:
                prompt = "I approve this exact command:\n" + world.command if approved else "Go."
                run(replace(world.client, argv=[*world.client.argv[:-1], prompt]))
                main_results(world)
            if not approved:
                assert not calls.exists() and not server.requests and not written
                assert world.output.read_text() == ""
                return
            _assert_written(world, action, calls, server, written)
    finally:
        close(world)


def _assert_written(world, action, calls, server, written):
    result = json.loads(world.output.read_text())
    assert result["result"] == action.upper().replace("-", "_") + "_PASS"
    assert len(written) == len(result["written"]) == 1
    assert result["written"][0]["payload_sha256"] == hashlib.sha256(written[0][1]).hexdigest()
    assert len(calls.read_text().splitlines()) == 3
    assert all(request["authorization"] == "Bearer disposable-pat" for request in server.requests)
    assert "SYNTHETIC_CANARY" not in world.output.read_text()
