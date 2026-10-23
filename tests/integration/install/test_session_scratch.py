"""Scratch ownership is recorded at creation and remains usable by later local commands."""

import json
import stat

from slopmeister.install.native_payload import _session_temporary
from tests.integration.install.installer_helpers import environment, install


def test_fresh_scratch_is_private_and_can_supply_a_nested_installer_tmpdir(tmp_path, monkeypatch):
    env = environment(tmp_path)
    first, second = (tmp_path / "sessions" / name for name in ("first", "second"))
    install(env, "--directory", "example-notes", str(first))
    state = first / ".slopmeister-config/state.json"
    saved = json.loads(state.read_text())
    scratch = first / saved["scratch"]
    assert scratch.name == ".slopmeister-tmp" and stat.S_IMODE(scratch.stat().st_mode) == 0o700
    assert saved["native_server_pins"] is True
    monkeypatch.setenv("SLOPMEISTER_SESSION_WORKSPACE", str(first))
    assert _session_temporary(scratch)
    before = state.read_bytes()
    selected = env | {"TMPDIR": str(scratch), "SLOPMEISTER_SESSION_WORKSPACE": str(first)}
    install(selected, "--directory", "example-notes", str(second))
    access = json.loads((second / ".claude/access-settings.json").read_text())
    assert str(scratch) in access["permissions"]["additionalDirectories"]
    assert state.read_bytes() == before


def test_unrecorded_scratch_is_not_adopted_as_a_temporary_root(tmp_path, monkeypatch):
    env = environment(tmp_path)
    first, second = (tmp_path / "sessions" / name for name in ("first", "second"))
    install(env, "--directory", "example-notes", str(first))
    state = first / ".slopmeister-config/state.json"
    saved = json.loads(state.read_text())
    saved.pop("scratch")
    state.write_text(json.dumps(saved))
    scratch = first / ".slopmeister-tmp"
    monkeypatch.setenv("SLOPMEISTER_SESSION_WORKSPACE", str(first))
    assert not _session_temporary(scratch)
    assert not second.exists()
