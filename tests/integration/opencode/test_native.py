"""OpenCode native evidence: the one session that is ours, and nothing that only looks like it."""

import os
from pathlib import Path

import pytest

from slopmeister.opencode import native
from tests.support import opencode_fake

PROMPT = "Create hello.txt, then stop."


def _world(tmp_path: Path, sessions: list[dict], exports: dict) -> tuple[str, dict]:
    fake = tmp_path / "bin"
    env = opencode_fake.install(fake, {"sessions": sessions, "exports": exports})
    env = {**os.environ, **env}
    return str(fake / "opencode"), env


def _session(workspace: Path, session: str, created: int) -> dict:
    return {"id": session, "directory": os.path.realpath(workspace), "created": created}


def test_finds_the_single_session_with_the_exact_kickoff(tmp_path):
    workspace = tmp_path / "wt"
    workspace.mkdir()
    real = os.path.realpath(workspace)
    exports = {"ses_a": opencode_fake.exported("ses_a", real, PROMPT)}
    binary, env = _world(tmp_path, [_session(workspace, "ses_a", 2000)], exports)
    _, found = native.find(native.Store(binary, workspace, env), PROMPT, 1000)
    assert found["session"] == "ses_a"
    assert found["directory"] == real
    assert found["models"] == ["prov/model-a"]
    assert found["finish"] == "stop"


def test_quote_wrapped_kickoff_is_not_delivery(tmp_path):
    """Escaping bug: `opencode run` stores argument prompts wrapped in quotes."""
    workspace = tmp_path / "wt"
    workspace.mkdir()
    real = os.path.realpath(workspace)
    exports = {"ses_a": opencode_fake.exported("ses_a", real, f'"{PROMPT}"')}
    binary, env = _world(tmp_path, [_session(workspace, "ses_a", 2000)], exports)
    with pytest.raises(native.Blocked, match="no native evidence: 0 sessions"):
        native.find(native.Store(binary, workspace, env), PROMPT, 1000)


@pytest.mark.parametrize(
    ("created", "count"),
    [((2000, 3000), "2 sessions"), ((500, 500), "0 sessions")],
    ids=["two-matching-sessions", "sessions-before-launch"],
)
def test_ambiguous_or_stale_sessions_refuse(tmp_path, created, count):
    """Escaping bug: a manual OpenCode session in the worktree is attributed as ours."""
    workspace = tmp_path / "wt"
    workspace.mkdir()
    real = os.path.realpath(workspace)
    ids = ("ses_a", "ses_b")
    rows = [_session(workspace, sid, when) for sid, when in zip(ids, created, strict=True)]
    exports = {sid: opencode_fake.exported(sid, real, PROMPT) for sid in ids}
    binary, env = _world(tmp_path, rows, exports)
    with pytest.raises(native.Blocked, match=count):
        native.find(native.Store(binary, workspace, env), PROMPT, 1000)


def test_other_directories_are_ignored(tmp_path):
    workspace = tmp_path / "wt"
    workspace.mkdir()
    other = tmp_path / "other"
    exports = {"ses_o": opencode_fake.exported("ses_o", str(other), PROMPT)}
    rows = [{"id": "ses_o", "directory": str(other), "created": 2000}]
    binary, env = _world(tmp_path, rows, exports)
    with pytest.raises(native.Blocked, match="0 sessions"):
        native.find(native.Store(binary, workspace, env), PROMPT, 1000)


def test_provider_names_come_from_the_config_and_never_values(tmp_path):
    config = tmp_path / "opencode.json"
    config.write_text('{"provider":{"p":{"options":{"apiKey":"{env:FAKE_KEY}"}}}}')
    env = {"OPENCODE_CONFIG": str(config)}
    assert native.provider_names(env) == ["FAKE_KEY"]
    with pytest.raises(native.Blocked, match="provider variable FAKE_KEY unset"):
        native.require_provider(env)
    assert native.require_provider({**env, "FAKE_KEY": "value"}) == ["FAKE_KEY"]


def test_child_env_carries_names_rules_and_disables_claude_files():
    """Escaping bug: OpenCode loads the operator's Claude skills or runs without deny rules."""
    rules = native.permission(edit=False)
    source = {"PATH": "/bin", "FAKE_KEY": "v" * 20, "OTHER": "x"}
    env = native.child_env(source, ["FAKE_KEY"], rules)
    assert set(env) == {
        "PATH",
        "FAKE_KEY",
        "OPENCODE_DISABLE_CLAUDE_CODE",
        "OPENCODE_CONFIG_CONTENT",
    }
    assert env["OPENCODE_DISABLE_CLAUDE_CODE"] == "1"
    assert '"op read *":"deny"' in env["OPENCODE_CONFIG_CONTENT"]
    assert '"edit":"deny"' in env["OPENCODE_CONFIG_CONTENT"]


def test_scrub_removes_an_opaque_value_everywhere(tmp_path):
    """Escaping bug: an echoed provider key reaches a quoted report that redact() cannot see."""
    secret = "Zq8vN1opaqueValue9x"
    (tmp_path / "a").mkdir()
    (tmp_path / "a/stderr.log").write_text(f"auth failed for {secret}\n")
    (tmp_path / "events.jsonl").write_text(f'{{"text":"{secret}"}}\n')
    subject = tmp_path / "checkout"
    subject.mkdir()
    (subject / "leaked.txt").write_text(secret)
    native.scrub(tmp_path, [secret], subject)
    for path in tmp_path.rglob("*"):
        if path.is_file() and not path.is_relative_to(subject):
            assert secret not in path.read_text()
    # The subject is never rewritten by the runner, a leaked value there stays for the tester.
    assert (subject / "leaked.txt").read_text() == secret


def test_empty_session_list_means_no_sessions(tmp_path):
    """Bug: OpenCode prints nothing for a project without sessions and the launcher crashes."""
    workspace = tmp_path / "wt"
    workspace.mkdir()
    fake = tmp_path / "bin"
    opencode_fake.install(fake, {"list_raw": ""})
    store = native.Store(str(fake / "opencode"), workspace, dict(os.environ))
    assert native.sessions(store) == []
    with pytest.raises(native.Blocked, match="0 sessions"):
        native.find(store, PROMPT, 0)


def test_incomplete_export_is_named_not_a_decode_crash(tmp_path):
    """Bug: a cut-short export surfaces as a raw JSON error with no reason or fix."""
    workspace = tmp_path / "wt"
    workspace.mkdir()
    real = os.path.realpath(workspace)
    fake = tmp_path / "bin"
    exports = {"ses_a": opencode_fake.exported("ses_a", real, PROMPT)}
    opencode_fake.install(fake, {"exports": exports, "export_cut": 40})
    store = native.Store(str(fake / "opencode"), workspace, dict(os.environ))
    with pytest.raises(native.Blocked, match="opencode export ses_a returned incomplete JSON"):
        native.export(store, "ses_a")
