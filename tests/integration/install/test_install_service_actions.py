"""Installation snapshots selected action payloads in both workspace shapes."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from slopmeister.install import snapshot
from tests.integration.install.helpers import ROOT, profile, unlock_deliveries
from tests.support.repos import git, scratch_repo

SAFE_ENV = ("PATH", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR")


def _fixture(tmp_path, shape, selected="jira-read"):
    home = tmp_path / "home"
    private = home / ".config/slopmeister/access/example-app"
    private.mkdir(parents=True)
    actions = [selected] if isinstance(selected, str) else selected
    for action in {value.replace("-write", "-read") for value in actions}:
        config = private / (action + ".json")
        config.write_text(json.dumps(profile("example-app") | {"action": action}))
        config.chmod(0o600)
    declarations = tmp_path / "plots/example-app"
    declarations.mkdir(parents=True)
    declaration = (
        '[plot]\nbase="code"\n[target]\ntasks="manual"\n'
        f'service_actions={json.dumps(actions)}\n[target.repository]\ncommit="allow"\n'
        "[slots]\nnone=true\n"
    )
    (declarations / "plot.toml").write_text(declaration)
    env = {key: os.environ[key] for key in SAFE_ENV if key in os.environ} | {
        "HOME": str(home),
        "PLOT_DECLARATIONS": str(declarations.parent),
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    if shape == "directory":
        return tmp_path / "workspace", "--directory", env
    repo = scratch_repo(tmp_path / "repo")
    workspace = repo / ".worktrees/subject"
    git(repo, "worktree", "add", "-q", "-b", "subject", str(workspace))
    return workspace, "--prepare", env


def _command(env, *args, ok=True, admission_error=None):
    from slopmeister.cli import main

    codex = Path(env["HOME"]) / ".local/bin/codex"
    if not codex.is_symlink():
        codex.parent.mkdir(parents=True, exist_ok=True)
        codex.symlink_to(Path.home() / ".local/bin/codex")
    stdout, stderr = io.StringIO(), io.StringIO()
    with (
        patch.dict(os.environ, env, clear=True),
        patch("slopmeister.install.prepare.admit", side_effect=admission_error),
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        code = main(["install", *args])
    result = SimpleNamespace(returncode=code, stdout=stdout.getvalue(), stderr=stderr.getvalue())
    assert (result.returncode == 0) == ok, result.stderr + result.stdout
    return result


def _assert_payload(workspace):
    assert "approvals_reviewer" not in (workspace / ".codex/config.toml").read_text()
    instructions = (workspace / "AGENTS.md").read_text()
    assert "Codex sessions use `on-request` with an automatic reviewer" in instructions
    assert "An automatic review decision is not operator approval" in instructions
    assert "operator as reviewer" not in instructions
    settings = json.loads((workspace / ".claude/access-settings.json").read_text())
    assert settings["permissions"]["ask"]
    assert "internal service-account document retrieval" in str(settings["autoMode"])
    for tool in ("codex", "claude"):
        delivered = workspace / ("." + tool) / "service-actions/jira-read"
        assert (delivered / "service_actions/openssl.cnf").is_file()
        assert json.loads((delivered / "config.json").read_text())["plot"] == "example-app"
        assert not list(delivered.glob("*.env"))
        assert delivered.stat().st_mode & 0o777 == 0o555
        for path in delivered.rglob("*"):
            mode = path.stat().st_mode & 0o777
            assert mode == (
                0o555 if path.is_dir() else 0o400 if path.name == "config.json" else 0o444
            )


def _assert_drift(workspace, env):
    for tool in (".codex", ".claude"):
        for name in ("supervisor.py", "openssl.cnf"):
            target = workspace / tool / "service-actions/jira-read/service_actions" / name
            original = target.read_bytes()
            target.chmod(0o644)
            _command(env, "--check", "example-app", str(workspace), ok=False)
            target.write_bytes(original + b"\n# tampered fixture\n")
            target.chmod(0o444)
            _command(env, "--check", "example-app", str(workspace), ok=False)
            target.chmod(0o644)
            target.write_bytes(original)
            target.chmod(0o444)
            _command(env, "--check", "example-app", str(workspace))


def _assert_manifest(workspace, shape):
    if shape == "directory":
        state_dir = workspace / ".slopmeister-config"
    else:
        state_dir = Path(git(workspace, "rev-parse", "--git-dir").strip()) / "slopmeister-config"
    manifest = json.loads((state_dir / snapshot.DIRECTORY / snapshot.MANIFEST).read_text())
    sources = ROOT / "slopmeister/session/service_actions"
    expected = {
        str(path.relative_to(ROOT)): snapshot.digest(path)
        for path in sources.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    assert {name: manifest[name] for name in expected} == expected
    for tool in (".codex", ".claude"):
        delivered = workspace / tool / "service-actions/jira-read"
        assert (delivered / "entry.py").read_bytes() == (sources / "entry.py").read_bytes()
        for source in (p for p in sources.iterdir() if p.suffix in (".py", ".cnf")):
            if source.name in ("entry.py", "native_tool.py"):
                assert (delivered / source.name).read_bytes() == source.read_bytes()
                continue
            assert (delivered / "service_actions" / source.name).read_bytes() == source.read_bytes()


@pytest.mark.parametrize("shape", ["directory", "worktree"])
def test_installer_snapshots_selected_payload_and_rejects_drift(tmp_path, shape):
    workspace, action, env = _fixture(tmp_path, shape)
    try:
        _command(env, action, "example-app", str(workspace))
        _command(env, "--check", "example-app", str(workspace))
        _assert_payload(workspace)
        _assert_manifest(workspace, shape)
        _assert_drift(workspace, env)
        if shape == "worktree":
            assert not git(workspace, "status", "--porcelain")
    finally:
        unlock_deliveries(tmp_path)


@pytest.mark.parametrize("shape", ["directory", "worktree"])
def test_missing_python_or_curl_refuses_before_directory_or_worktree_delivery(tmp_path, shape):
    workspace, action, env = _fixture(tmp_path, shape)
    try:
        result = _command(
            env,
            action,
            "example-app",
            str(workspace),
            ok=False,
            admission_error=ValueError(
                "selected service action prerequisites are missing before session creation: "
                "/usr/bin/curl; provider was not contacted"
            ),
        )
        assert "before session creation" in result.stderr
        assert "provider was not contacted" in result.stderr
        if shape == "directory":
            assert not workspace.exists()
        else:
            assert not git(workspace, "status", "--porcelain")
            assert not (workspace / ".codex").exists()
            assert not (workspace / ".claude").exists()
    finally:
        unlock_deliveries(tmp_path)


@pytest.mark.parametrize("shape", ["directory", "worktree"])
@pytest.mark.parametrize("selected", ["jira-write", "confluence-write"])
def test_declared_write_prepares_with_native_gates_for_both_tools(tmp_path, shape, selected):
    """Bug: the retired terminal refusal prevents plots from delivering guarded writes."""
    workspace, action, env = _fixture(tmp_path, shape, selected)
    try:
        _command(env, action, "example-app", str(workspace))
        _command(env, "--check", "example-app", str(workspace))
        settings = json.loads((workspace / ".claude/access-settings.json").read_text())
        config = (workspace / ".codex/config.toml").read_text()
        for tool in (".claude", ".codex"):
            entry = workspace / tool / "service-actions" / selected / "entry.py"
            assert entry.is_file() and entry.stat().st_mode & 0o777 == 0o444
            assert entry.with_name("native_tool.py").is_file()
        assert f"mcp__{selected.replace('-', '_')}__run" in settings["permissions"]["ask"]
        assert f"[mcp_servers.{selected.replace('-', '_')}.tools.run]" in config
        assert 'approval_mode="prompt"' in config
    finally:
        unlock_deliveries(tmp_path)


def test_named_atlassian_plot_delivers_all_four_selected_actions(tmp_path):
    """Bug: writes work in a synthetic declaration but never reach the actual intended plots."""
    plot = "example-client"
    workspace, action, env = _fixture(tmp_path, "worktree")
    env["PLOT_DECLARATIONS"] = str(ROOT / "plots")
    actions = ("jira-read", "confluence-read", "jira-write", "confluence-write")
    directory = Path(env["HOME"]) / ".config/slopmeister/access" / plot
    directory.mkdir()
    for selected in ("jira-read", "confluence-read"):
        path = directory / (selected + ".json")
        path.write_text(json.dumps(profile(plot) | {"action": selected}))
        path.chmod(0o600)
    try:
        _command(env, action, plot, str(workspace))
        _command(env, "--check", plot, str(workspace))
        for tool in (".claude", ".codex"):
            assert all(
                (workspace / tool / "service-actions" / a / "entry.py").is_file() for a in actions
            )
        rules = (workspace / ".codex/rules/service-actions.rules").read_text()
        config = (workspace / ".codex/config.toml").read_text()
        for selected in actions:
            suffix = "/entry.py" if selected.endswith("-read") else "/native_tool.py"
            assert "/" + selected + suffix in (rules if selected.endswith("-read") else config)
    finally:
        unlock_deliveries(tmp_path)
