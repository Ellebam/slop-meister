"""Dispatcher delivery keeps declared Jira profiles and native approvals isolated."""

import json

import pytest

from slopmeister.install.service_actions import ActionContext, action_payload
from tests.integration.install.helpers import fixture, profile, unlock_deliveries
from tests.integration.install.test_install_service_actions import _command


def _selected(tmp_path):
    root, profiles, _ = fixture(tmp_path)
    contexts = []
    for name in ("example", "second"):
        path = profiles / name / "jira-read.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(profile(name) | {"origin": f"https://{name}.invalid"}))
        path.chmod(0o600)
        contexts.append(
            ActionContext(
                root,
                name,
                {"service_actions": ["jira-read"]},
                tmp_path / "session",
                profiles,
                namespaced=True,
            )
        )
    return contexts


def test_multiple_plot_entries_keep_their_profiles_and_both_native_prompts(tmp_path):
    """Bug: the second Jira payload overwrites the first profile or native rule file."""
    contexts = _selected(tmp_path)
    files, permissions, instructions = action_payload(contexts[0], contexts)
    rules = files[".codex/rules/service-actions.rules"][0].decode()
    for context in contexts:
        for native in (".codex", ".claude"):
            prefix = f"{native}/service-actions/{context.plot}/jira-read/"
            assert json.loads(files[prefix + "config.json"][0])["plot"] == context.plot
            entry = str(context.workspace / prefix / "entry.py")
            assert entry in rules and any(entry in ask for ask in permissions["ask"])
            assert entry in instructions
    assert instructions.count("Use only the approved action.") == 1


@pytest.mark.parametrize("unsafe", ["missing", "mode", "plot", "symlink"])
def test_one_unusable_profile_does_not_hide_the_other_reader(tmp_path, unsafe):
    """Bug: a missing or invalid profile prevents every dispatcher function from launching."""
    contexts = _selected(tmp_path)
    path = contexts[0].profile_root / "second/jira-read.json"
    if unsafe == "missing":
        path.unlink()
    elif unsafe == "mode":
        path.chmod(0o644)
    elif unsafe == "plot":
        path.write_text(json.dumps(profile("wrong")))
    else:
        saved = path.with_suffix(".saved")
        path.rename(saved)
        path.symlink_to(saved)
    files, permissions, instructions = action_payload(contexts[0], contexts)
    assert ".codex/service-actions/example/jira-read/config.json" in files
    assert not any("service-actions/second/" in name for name in files)
    assert not any("service-actions/second/" in rule for rule in permissions["ask"])
    assert "second: Jira reader unavailable" in instructions


def _world(tmp_path, monkeypatch):
    home, declarations = tmp_path / "home", tmp_path / "plots"
    monkeypatch.setenv("HOME", str(home))
    for name, actions in (
        ("slopmeister", []),
        ("example-app", []),
        ("one", ["jira-read", "confluence-read"]),
        ("two", ["jira-read"]),
        ("other", ["confluence-read"]),
    ):
        directory = declarations / name
        directory.mkdir(parents=True)
        text = '[plot]\nbase="code"\n[target]\ntasks="manual"\n'
        text += f'service_actions={json.dumps(actions)}\n[target.repository]\ncommit="allow"\n'
        (directory / "plot.toml").write_text(text + "[slots]\nnone=true\n")
    private = home / ".config/slopmeister/access/one"
    private.mkdir(parents=True)
    path = private / "jira-read.json"
    path.write_text(json.dumps(profile("one")))
    path.chmod(0o600)
    env = {"HOME": str(home), "PLOT_DECLARATIONS": str(declarations)}
    return env, tmp_path / "dispatcher"


def test_fresh_dispatcher_delivers_only_declared_jira_reads_and_verifies_snapshot(
    tmp_path, monkeypatch
):
    """Bug: dispatcher delivery adds writes/Confluence or leaves entries outside the snapshot."""
    env, workspace = _world(tmp_path, monkeypatch)
    try:
        _command(env, "--directory", "slopmeister", str(workspace), "--dispatcher-jira")
        _command(env, "--check", "slopmeister", str(workspace))
        for native in (".claude", ".codex"):
            root = workspace / native / "service-actions"
            assert (root / "one/jira-read").stat().st_mode & 0o777 == 0o555
            assert not any(p.name in ("confluence-read", "jira-write") for p in root.rglob("*"))
        assert "two: Jira reader unavailable" in (workspace / "AGENTS.md").read_text()
        source = workspace / ".codex/service-actions/one/jira-read/entry.py"
        source.chmod(0o644)
        _command(env, "--check", "slopmeister", str(workspace), ok=False)
    finally:
        unlock_deliveries(tmp_path)


def test_missing_reader_prerequisites_preserve_dispatcher_launch(tmp_path, monkeypatch):
    """Bug: missing op/curl/fixed Python prevents unrelated GitHub backlog and status use."""
    env, workspace = _world(tmp_path, monkeypatch)
    _command(
        env,
        "--directory",
        "slopmeister",
        str(workspace),
        "--dispatcher-jira",
        admission_error=ValueError("selected service action prerequisites are missing"),
    )
    assert not (workspace / ".codex/service-actions").exists()
    assert "one: Jira reader unavailable" in (workspace / "AGENTS.md").read_text()
    _command(env, "--check", "slopmeister", str(workspace))


def test_no_valid_profile_grants_no_selected_action_exception(tmp_path, monkeypatch):
    """Bug: an entirely unavailable reader set still enables the selected-action exception."""
    env, workspace = _world(tmp_path, monkeypatch)
    (tmp_path / "home/.config/slopmeister/access/one/jira-read.json").unlink()
    _command(env, "--directory", "slopmeister", str(workspace), "--dispatcher-jira")
    access = json.loads((workspace / ".claude/access-settings.json").read_text())
    assert "Selected fixed service read action" not in str(access.get("autoMode", {}))
    assert not (workspace / ".codex/service-actions").exists()


def test_dispatcher_selection_cannot_be_requested_in_worker_or_check_mode(tmp_path, monkeypatch):
    """Bug: an aggregation flag turns an ordinary worker/check into a cross-plot reader."""
    env, workspace = _world(tmp_path, monkeypatch)
    worker = _command(
        env, "--directory", "example-app", str(workspace), "--dispatcher-jira", ok=False
    )
    check = _command(env, "--check", "slopmeister", str(workspace), "--dispatcher-jira", ok=False)
    assert "dispatcher Jira delivery requires a fresh Slopmeister directory" in worker.stderr
    assert "dispatcher Jira delivery requires a fresh Slopmeister directory" in check.stderr
    assert not workspace.exists()
